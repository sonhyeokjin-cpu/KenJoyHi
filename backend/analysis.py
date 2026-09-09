"""Pure analysis jobs used by both HTTP and background-worker routes."""
import numpy as np

from .db import DB_PATH, get_timeseries_data, save_timeseries_data
from .derived import execute_derived_parameter
from .filters import (apply_bandpass_filter, apply_lowpass_filter,
                      apply_moving_average, apply_rms, get_filter_info)


def _raw_channel(name, start=-np.inf, end=np.inf):
    data = get_timeseries_data(name, start, end)
    time = np.asarray(data.get('time', []), dtype=np.float64)
    values = np.asarray(data.get('value', []), dtype=np.float64)
    if time.size != values.size or time.size == 0:
        raise ValueError(f'No valid data for parameter: {name}')
    return time, values


def _sampling_frequency(time):
    dt = np.diff(time)
    dt = dt[np.isfinite(dt) & (dt > 0)]
    if not dt.size:
        raise ValueError('Time axis must contain increasing samples')
    return 1.0 / float(np.median(dt))


def align_values(reference_time, source_time, source_values, policy='linear', max_gap=None):
    """Align a source channel to reference timestamps with an explicit policy."""
    if policy not in ('linear', 'nearest', 'hold-last'):
        raise ValueError('alignment must be linear, nearest, or hold-last')
    finite = np.isfinite(source_time) & np.isfinite(source_values)
    source_time, source_values = source_time[finite], source_values[finite]
    if source_time.size < 1:
        return np.full(reference_time.shape, np.nan)
    right = np.searchsorted(source_time, reference_time, side='left')
    left = np.maximum(right - 1, 0)
    right_clip = np.minimum(right, source_time.size - 1)
    outside = (reference_time < source_time[0]) | (reference_time > source_time[-1])
    if policy == 'nearest':
        choose_right = np.abs(source_time[right_clip] - reference_time) < np.abs(reference_time - source_time[left])
        index = np.where(choose_right, right_clip, left)
        result = source_values[index].astype(float, copy=True)
    elif policy == 'hold-last':
        hold_index = np.clip(np.searchsorted(source_time, reference_time, side='right') - 1,
                             0, source_time.size - 1)
        result = source_values[hold_index].astype(float, copy=True)
    else:
        result = np.interp(reference_time, source_time, source_values)
    result[outside] = np.nan
    if max_gap is not None and np.isfinite(max_gap) and max_gap > 0:
        distance = np.minimum(np.abs(reference_time - source_time[left]),
                              np.abs(source_time[right_clip] - reference_time))
        result[distance > max_gap] = np.nan
    return result


def filter_channel(payload):
    parameter = payload.get('parameter')
    filter_type = payload.get('filter_type')
    params = payload.get('params') or {}
    if not parameter or not filter_type:
        raise ValueError('parameter and filter_type are required')
    time, values = _raw_channel(parameter)
    finite = np.isfinite(time) & np.isfinite(values)
    time, values = time[finite], values[finite]
    if time.size < 2:
        raise ValueError('At least two finite samples are required')
    sampling_freq = _sampling_frequency(time)
    if filter_type == 'lpf':
        filtered = apply_lowpass_filter(values, params['cutoff_freq'], params['order'], sampling_freq)
        name = f"{parameter}_LPF_{params['cutoff_freq']}Hz_{params['order']}order"
    elif filter_type == 'bpf':
        filtered = apply_bandpass_filter(values, params['low_freq'], params['high_freq'],
                                         params['order'], sampling_freq)
        name = f"{parameter}_BPF_{params['low_freq']}_{params['high_freq']}Hz_{params['order']}order"
    elif filter_type == 'ma':
        filtered = apply_moving_average(values, params['window_size'], sampling_freq)
        name = f"{parameter}_MA_{params['window_size']}window"
    elif filter_type == 'rms':
        filtered = apply_rms(values, params['window_size'], sampling_freq)
        name = f"{parameter}_RMS_{params['window_size']}window"
    else:
        raise ValueError(f'Unknown filter type: {filter_type}')
    save_timeseries_data(name, time, np.asarray(filtered, dtype=np.float64), 0)
    info = get_filter_info(filter_type, {**params, 'time_data': time.tolist()})
    return {'parameter': name, 'filter_info': {'type': filter_type,
            'parameters': params, **info}, 'refresh_parameters': True}


def derived_channel(payload):
    name, code = payload.get('name'), payload.get('code')
    parameters = payload.get('parameters') or []
    policy = payload.get('alignment', 'linear')
    max_gap = payload.get('max_gap')
    if not name or not code or not parameters:
        raise ValueError('name, code, and parameters are required')
    reference_time = None
    values_by_name = {}
    for parameter in parameters:
        time, values = _raw_channel(parameter)
        if reference_time is None:
            reference_time = time
            values_by_name[parameter] = values
        else:
            values_by_name[parameter] = align_values(reference_time, time, values,
                                                     policy, max_gap)
    result = execute_derived_parameter(code, values_by_name)
    save_timeseries_data(name, reference_time, result, 0)
    return {'message': 'Derived parameter created successfully', 'parameter': name,
            'alignment': policy}


def fft_channel(payload):
    parameter = payload.get('parameter')
    start = float(payload.get('start', -np.inf))
    end = float(payload.get('end', np.inf))
    if not parameter:
        raise ValueError('parameter is required')
    time, values = _raw_channel(parameter, start, end)
    finite = np.isfinite(time) & np.isfinite(values)
    time, values = time[finite], values[finite]
    if time.size < 4:
        raise ValueError('At least four finite samples are required for FFT')
    dt = np.diff(time)
    median_dt = float(np.median(dt))
    if median_dt <= 0 or np.any(np.abs(dt - median_dt) > median_dt * 0.01):
        raise ValueError('FFT requires a nearly uniform time axis (within 1%)')
    count = min(values.size, 262_144)
    size = 1 << int(np.floor(np.log2(count)))
    values = values[:size] - np.mean(values[:size])
    spectrum = np.fft.rfft(values * np.hanning(size))
    frequency = np.fft.rfftfreq(size, median_dt)
    magnitude = 2.0 * np.abs(spectrum) / size
    return {'parameter': parameter, 'sample_count': size,
            'frequencies': frequency.tolist(), 'magnitudes': magnitude.tolist()}
