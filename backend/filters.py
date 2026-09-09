import numpy as np
from scipy import signal
import pandas as pd

def apply_lowpass_filter(data, cutoff_freq, order, sampling_freq):
    """
    Apply Butterworth low-pass filter to the data
    
    Args:
        data (numpy.ndarray): Input data
        cutoff_freq (float): Cutoff frequency in Hz
        order (int): Filter order
        sampling_freq (float): Sampling frequency in Hz
    
    Returns:
        numpy.ndarray: Filtered data
    """
    # 입력 데이터 검증
    if not isinstance(data, np.ndarray):
        raise ValueError("Input data must be numpy array")
    
    # 데이터 스케일 검증
    data_mean = np.mean(data)
    data_std = np.std(data)
    print(f"Input data stats: mean={data_mean}, std={data_std}")
    
    # 정규화된 주파수 계산 (0~1 사이 값)
    nyquist = sampling_freq / 2
    normal_cutoff = cutoff_freq / nyquist
    
    # 로깅 추가
    print(f"Filter parameters:")
    print(f"  Sampling frequency: {sampling_freq} Hz")
    print(f"  Nyquist frequency: {nyquist} Hz")
    print(f"  Cutoff frequency: {cutoff_freq} Hz")
    print(f"  Normalized cutoff: {normal_cutoff}")
    print(f"  Filter order: {order}")
    
    # 필터 계수 계산 (Butterworth 필터)
    b, a = signal.butter(order, normal_cutoff, btype='low', analog=False)
    
    # 필터 응답 확인
    w, h = signal.freqz(b, a, worN=1024)
    freq = w * sampling_freq / (2 * np.pi)
    
    # 통과대역과 차단대역의 게인 확인
    passband_mask = freq <= cutoff_freq
    stopband_mask = freq > cutoff_freq
    
    passband_gain = np.mean(np.abs(h[passband_mask]))
    stopband_gain = np.mean(np.abs(h[stopband_mask]))
    
    print(f"Filter response:")
    print(f"  Passband gain: {passband_gain}")
    print(f"  Stopband gain: {stopband_gain}")
    
    # 필터 적용 (일반 필터링)
    filtered_data = signal.lfilter(b, a, data)
    
    # 출력 데이터 스케일 검증
    filtered_mean = np.mean(filtered_data)
    filtered_std = np.std(filtered_data)
    print(f"Filtered data stats: mean={filtered_mean}, std={filtered_std}")
    
    # 데이터 스케일 비교
    scale_ratio = filtered_std / data_std if data_std != 0 else 0
    print(f"Data scale ratio (filtered/original): {scale_ratio}")
    
    return filtered_data

def apply_bandpass_filter(data, low_freq, high_freq, order, sampling_freq):
    """
    Apply Butterworth band-pass filter to the data
    
    Args:
        data (numpy.ndarray): Input data
        low_freq (float): Lower cutoff frequency in Hz
        high_freq (float): Upper cutoff frequency in Hz
        order (int): Filter order
        sampling_freq (float): Sampling frequency in Hz
    
    Returns:
        numpy.ndarray: Filtered data
    """
    # 입력 데이터 검증
    if not isinstance(data, np.ndarray):
        raise ValueError("Input data must be numpy array")
    
    # 데이터 스케일 검증
    data_mean = np.mean(data)
    data_std = np.std(data)
    print(f"Input data stats: mean={data_mean}, std={data_std}")
    
    # 정규화된 주파수 계산 (0~1 사이 값)
    nyquist = sampling_freq / 2
    low = low_freq / nyquist
    high = high_freq / nyquist
    
    # 로깅 추가
    print(f"Filter parameters:")
    print(f"  Sampling frequency: {sampling_freq} Hz")
    print(f"  Nyquist frequency: {nyquist} Hz")
    print(f"  Frequency range: {low_freq}-{high_freq} Hz")
    print(f"  Normalized range: {low}-{high}")
    print(f"  Filter order: {order}")
    
    # 필터 계수 계산 (Butterworth 필터)
    b, a = signal.butter(order, [low, high], btype='band', analog=False)
    
    # 필터 응답 확인
    w, h = signal.freqz(b, a, worN=1024)
    freq = w * sampling_freq / (2 * np.pi)
    
    # 통과대역과 차단대역의 게인 확인
    passband_mask = (freq >= low_freq) & (freq <= high_freq)
    stopband_mask = ~passband_mask
    
    passband_gain = np.mean(np.abs(h[passband_mask]))
    stopband_gain = np.mean(np.abs(h[stopband_mask]))
    
    print(f"Filter response:")
    print(f"  Passband gain: {passband_gain}")
    print(f"  Stopband gain: {stopband_gain}")
    
    # 필터 적용 (일반 필터링)
    filtered_data = signal.lfilter(b, a, data)
    
    # 출력 데이터 스케일 검증
    filtered_mean = np.mean(filtered_data)
    filtered_std = np.std(filtered_data)
    print(f"Filtered data stats: mean={filtered_mean}, std={filtered_std}")
    
    # 데이터 스케일 비교
    scale_ratio = filtered_std / data_std if data_std != 0 else 0
    print(f"Data scale ratio (filtered/original): {scale_ratio}")
    
    return filtered_data

def apply_moving_average(data, window_size, sampling_freq):
    """
    Apply moving average filter to the data
    
    Args:
        data (numpy.ndarray): Input data
        window_size (int): Window size in samples
        sampling_freq (float): Sampling frequency in Hz
    
    Returns:
        numpy.ndarray: Filtered data
    """
    # 입력 데이터 검증
    if not isinstance(data, np.ndarray):
        raise ValueError("Input data must be numpy array")
    
    # 데이터 스케일 검증
    data_mean = np.mean(data)
    data_std = np.std(data)
    print(f"Input data stats: mean={data_mean}, std={data_std}")
    
    # 이동평균 필터 계수 계산
    b = np.ones(window_size) / window_size
    a = np.array([1.0])
    
    # 필터 응답 확인
    w, h = signal.freqz(b, a, worN=1024)
    freq = w * sampling_freq / (2 * np.pi)
    
    # DC 게인 확인
    dc_gain = np.abs(h[0])
    print(f"DC gain: {dc_gain}")
    
    # 필터 적용
    filtered_data = signal.lfilter(b, a, data)
    
    # 출력 데이터 스케일 검증
    filtered_mean = np.mean(filtered_data)
    filtered_std = np.std(filtered_data)
    print(f"Filtered data stats: mean={filtered_mean}, std={filtered_std}")
    
    # 데이터 스케일 비교
    scale_ratio = filtered_std / data_std if data_std != 0 else 0
    print(f"Data scale ratio (filtered/original): {scale_ratio}")
    
    return filtered_data

def apply_rms(data, window_size, sampling_freq):
    """
    Apply RMS filter to the data.
    
    Args:
        data (numpy.ndarray): Input data.
        window_size (int): The size of the window.
        sampling_freq (float): Sampling frequency in Hz (for consistency, not used).
        
    Returns:
        numpy.ndarray: Filtered data.
    """
    if not isinstance(data, np.ndarray):
        raise ValueError("Input data must be a numpy array.")
    
    if window_size <= 0:
        raise ValueError("Window size must be positive.")

    # Use pandas for efficient rolling RMS calculation
    series = pd.Series(data)
    rms = series.rolling(window=window_size).apply(lambda x: np.sqrt(np.mean(x**2)), raw=True)
    
    # The rolling operation introduces NaNs at the beginning. Fill them.
    rms = rms.fillna(0) 
    
    return rms.to_numpy()

def get_filter_info(filter_type, params):
    """
    Generate filter information dictionary
    
    Args:
        filter_type (str): Type of filter ('lpf', 'bpf', or 'ma')
        params (dict): Filter parameters
    
    Returns:
        dict: Filter information including formula and description
    """
    # Calculate sampling frequency from time data
    time_data = params.get('time_data', [])
    if len(time_data) >= 2:
        sampling_freq = 1.0 / (time_data[1] - time_data[0])
    else:
        sampling_freq = 512.0  # 기본값
    
    if filter_type == 'lpf':
        # Calculate filter coefficients
        nyquist = sampling_freq / 2
        normal_cutoff = params['cutoff_freq'] / nyquist
        b, a = signal.butter(params['order'], normal_cutoff, btype='low', analog=False)
        
        # Calculate frequency response
        w, h = signal.freqz(b, a, worN=1024)
        freq = w * sampling_freq / (2 * np.pi)
        magnitude = 20 * np.log10(np.abs(h))
        phase = np.unwrap(np.angle(h)) * 180 / np.pi
        
        # Calculate group delay for frequencies below cutoff frequency
        _, gd = signal.group_delay((b, a), w=w)
        
        # Patch: Remove non-finite values for JSON serialization (apply to gd too)
        finite_mask = np.isfinite(freq) & np.isfinite(magnitude) & np.isfinite(phase) & np.isfinite(gd)
        freq = freq[finite_mask]
        magnitude = magnitude[finite_mask]
        phase = phase[finite_mask]
        gd = gd[finite_mask]
        
        cutoff_mask = freq <= params['cutoff_freq']
        avg_delay = np.mean(gd[cutoff_mask]) / sampling_freq  # Convert to seconds
        
        # Format coefficients for display
        b_str = ', '.join([f'{x:.8f}' for x in b])
        a_str = ', '.join([f'{x:.8f}' for x in a])
        
        return {
            'formula': f"""차분 방정식:\ny[n] = {b[0]:.8f}x[n] + {b[1]:.8f}x[n-1] + ... + {b[-1]:.8f}x[n-{len(b)-1}] - {a[1]:.8f}y[n-1] - ... - {a[-1]:.8f}y[n-{len(a)-1}]""",
            'description': f"""필터 형식: IIR, Butterworth\n필터 타입: 저역통과(Low-pass)\n필터 차수: {params['order']}차 ({params['order']}th-order)\n샘플링 주파수: {sampling_freq:.2f}Hz\n차단 주파수: {params['cutoff_freq']}Hz\n예상 지연시간 (차단주파수 이하): {avg_delay*1000:.2f}ms\n필터 계수:\nb = [{b_str}]\na = [{a_str}]""",
            'frequency_response': {
                'freq': freq.tolist(),
                'magnitude': magnitude.tolist(),
                'phase': phase.tolist()
            }
        }
    
    elif filter_type == 'bpf':
        # Calculate filter coefficients
        nyquist = sampling_freq / 2
        low = params['low_freq'] / nyquist
        high = params['high_freq'] / nyquist
        b, a = signal.butter(params['order'], [low, high], btype='band', analog=False)
        
        # Calculate frequency response
        w, h = signal.freqz(b, a, worN=1024)
        freq = w * sampling_freq / (2 * np.pi)
        magnitude = 20 * np.log10(np.abs(h))
        phase = np.unwrap(np.angle(h)) * 180 / np.pi
        
        # Calculate group delay for passband frequencies
        _, gd = signal.group_delay((b, a), w=w)
        
        # Patch: Remove non-finite values for JSON serialization (apply to gd too)
        finite_mask = np.isfinite(freq) & np.isfinite(magnitude) & np.isfinite(phase) & np.isfinite(gd)
        freq = freq[finite_mask]
        magnitude = magnitude[finite_mask]
        phase = phase[finite_mask]
        gd = gd[finite_mask]
        
        passband_mask = (freq >= params['low_freq']) & (freq <= params['high_freq'])
        avg_delay = np.mean(gd[passband_mask]) / sampling_freq  # Convert to seconds
        
        # Format coefficients for display
        b_str = ', '.join([f'{x:.8f}' for x in b])
        a_str = ', '.join([f'{x:.8f}' for x in a])
        
        return {
            'formula': f"""차분 방정식:\ny[n] = {b[0]:.8f}x[n] + {b[1]:.8f}x[n-1] + ... + {b[-1]:.8f}x[n-{len(b)-1}] - {a[1]:.8f}y[n-1] - ... - {a[-1]:.8f}y[n-{len(a)-1}]""",
            'description': f"""필터 형식: IIR, Butterworth\n필터 타입: 대역통과(Band-pass)\n필터 차수: {params['order']}차 ({params['order']}th-order)\n샘플링 주파수: {sampling_freq:.2f}Hz\n주파수 범위: {params['low_freq']}Hz - {params['high_freq']}Hz\n예상 지연시간 (통과대역): {avg_delay*1000:.2f}ms\n필터 계수:\nb = [{b_str}]\na = [{a_str}]""",
            'frequency_response': {
                'freq': freq.tolist(),
                'magnitude': magnitude.tolist(),
                'phase': phase.tolist()
            }
        }
    
    elif filter_type == 'ma':
        # For moving average, coefficients are uniform
        window_size = params['window_size']
        b = np.ones(window_size) / window_size
        a = np.array([1.0])
        
        # Calculate frequency response
        w, h = signal.freqz(b, a, worN=1024)
        freq = w * sampling_freq / (2 * np.pi)
        magnitude = 20 * np.log10(np.abs(h))
        phase = np.unwrap(np.angle(h)) * 180 / np.pi
        # (moving average는 group delay 사용 안함)
        
        # Patch: Remove non-finite values for JSON serialization
        finite_mask = np.isfinite(freq) & np.isfinite(magnitude) & np.isfinite(phase)
        freq = freq[finite_mask]
        magnitude = magnitude[finite_mask]
        phase = phase[finite_mask]
        
        # Calculate delay time for moving average (half of window size)
        avg_delay = (window_size / 2) / sampling_freq  # Convert to seconds
        
        # Format coefficients for display
        b_str = ', '.join([f'{x:.8f}' for x in b])
        
        return {
            'formula': f"""차분 방정식:\ny[n] = (1/{window_size})(x[n] + x[n-1] + ... + x[n-{window_size-1}])""",
            'description': f"""필터 형식: FIR\n필터 타입: 이동평균(Moving Average)\n샘플링 주파수: {sampling_freq:.2f}Hz\n윈도우 크기: {window_size} 샘플\n예상 지연시간 (윈도우 크기/2): {avg_delay*1000:.2f}ms\n필터 계수:\nb = [{b_str}]\na = [1.00000000]""",
            'frequency_response': {
                'freq': freq.tolist(),
                'magnitude': magnitude.tolist(),
                'phase': phase.tolist()
            }
        }
    
    elif filter_type == 'rms':
        window_size = params['window_size']
        avg_delay = (window_size / 2) / sampling_freq  # Convert to seconds

        return {
            'formula': f"y[n] = sqrt( (1/{window_size}) * (x[n]^2 + x[n-1]^2 + ... + x[n-{window_size-1}]^2) )",
            'description': f"Filter Type: Root Mean Square (RMS)\nSampling Frequency: {sampling_freq:.2f}Hz\nWindow Size: {window_size} samples\nEstimated Delay (window_size/2): {avg_delay*1000:.2f}ms",
            'frequency_response': {
                'freq': [],
                'magnitude': [],
                'phase': []
            }
        }
    
    return {
        'formula': 'Unknown filter type',
        'description': 'Unknown filter type'
    } 