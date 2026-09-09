import numpy as np
from scipy import signal
import pandas as pd
import re
import ast
import logging
import operator
import scipy.fft as sp_fft

logger = logging.getLogger(__name__)

# Define safe globals for parameter derivation
safe_globals = {
    # Basic operators
    'add': operator.add,
    'sub': operator.sub,
    'mul': operator.mul,
    'truediv': operator.truediv,
    'floordiv': operator.floordiv,
    'mod': operator.mod,
    'pow': operator.pow,
    'neg': operator.neg,
    'pos': operator.pos,
    'abs': operator.abs,
    'round': round,
    
    # Bitwise operators
    'and_': operator.and_,
    'or_': operator.or_,
    'xor': operator.xor,
    'invert': operator.invert,
    'lshift': operator.lshift,
    'rshift': operator.rshift,
    
    # Comparison operators
    'eq': operator.eq,
    'ne': operator.ne,
    'lt': operator.lt,
    'le': operator.le,
    'gt': operator.gt,
    'ge': operator.ge,
    
    # Mathematical functions
    'np': np,
    'mean': np.mean,
    'std': np.std,
    'abs': np.abs,
    'sqrt': np.sqrt,
    'diff': lambda x, direction=None: np.diff(x, prepend=x[0]),
    'log': np.log,
    'log10': np.log10,
    'log2': np.log2,
    'exp': np.exp,
    'sin': np.sin,
    'cos': np.cos,
    'tan': np.tan,
    'arcsin': np.arcsin,
    'arccos': np.arccos,
    'arctan': np.arctan,
    'sinh': np.sinh,
    'cosh': np.cosh,
    'tanh': np.tanh,
    'deg2rad': np.deg2rad,
    'rad2deg': np.rad2deg,
    'cumsum': np.cumsum,
    'cumprod': np.cumprod,
    'clip': np.clip,
    
    # Bitwise operations
    'bitwise_and': np.bitwise_and,
    'bitwise_or': np.bitwise_or,
    'bitwise_xor': np.bitwise_xor,
    'bitwise_not': np.bitwise_not,
    'left_shift': np.left_shift,
    'right_shift': np.right_shift,
    'bit_count': lambda x: np.binary_repr(x).count('1'),
    'is_power_of_2': lambda x: x > 0 and (x & (x - 1)) == 0,
    'next_power_of_2': lambda x: 1 << (x - 1).bit_length(),
    
    # Signal processing
    'butter_lowpass': signal.butter,
    'moving_average': lambda x, w: pd.Series(x).rolling(w, min_periods=1).mean().to_numpy(),
    'bit_extract': lambda x, bit: (x >> bit) & 1,
    'detect_blips': lambda x, threshold: np.where(np.abs(np.diff(x, prepend=x[0])) > threshold, 1, 0),
    'generate_blip_series': lambda x, threshold: np.cumsum(np.where(np.abs(np.diff(x, prepend=x[0])) > threshold, 1, 0)),
    'segment_by_blip': lambda x, blips: np.split(x, np.where(blips)[0]),
    'compute_dynamic_load': lambda segments: np.array([np.max(seg) - np.min(seg) for seg in segments]),
    'compute_fft': lambda x: np.abs(np.fft.fft(x)),
    'remove_n_rev': lambda x, n: x % n,
    'saturation_clip': lambda x, min_val, max_val: np.clip(x, min_val, max_val),
    'remove_offset': lambda x: x - np.mean(x),
    'integration': lambda x, dt: np.cumsum(x) * dt,
    'derivative': lambda x, dt: np.gradient(x, dt),
    'resample': lambda x, old_t, new_t: np.interp(new_t, old_t, x),
    'fft_peak': lambda x: np.argmax(np.abs(np.fft.fft(x))),
    
    # Binary operations
    'extract_bits': lambda x, start, end: (x >> start) & ((1 << (end - start)) - 1),
    'check_parity': lambda x: np.sum(x & 1) % 2,
    'bcd_to_int': lambda x: int(str(x), 16),
    'gray_to_binary': lambda x: x ^ (x >> 1),
    'mil1553_is_rt_to_bc': lambda x: (x >> 10) & 1,
    'mil1553_subaddress': lambda x: (x >> 5) & 0x1F,
    'mil1553_word_count': lambda x: x & 0x1F,
    'arinc_label': lambda x: (x >> 17) & 0xFF,
    'arinc_sdi': lambda x: (x >> 9) & 0x3,
    'arinc_data': lambda x: x & 0x1FF,
    'arinc_ssm': lambda x: (x >> 10) & 0x3,
    
    # Statistical functions
    'rms': lambda x: np.sqrt(np.mean(np.square(x))),
    'moving_std': lambda x, w: pd.Series(x).rolling(w, min_periods=1).std().to_numpy(),
    'z_score': lambda x: (x - np.mean(x)) / np.std(x),
    'normalize': lambda x: (x - np.min(x)) / (np.max(x) - np.min(x)),
    'clip_outliers': lambda x, n_std: np.clip(x, np.mean(x) - n_std * np.std(x), np.mean(x) + n_std * np.std(x)),
    'threshold_crossing': lambda x, threshold: np.where(x > threshold, 1, 0),
    'state_duration': lambda x: np.diff(np.where(np.diff(np.concatenate(([0], x, [0]))))[0]),
    'dwell_time_above': lambda x, threshold: np.sum(x > threshold),
    'peak_to_peak': lambda x: np.max(x) - np.min(x),
    'zero_crossings': lambda x: np.sum(np.diff(np.signbit(x))),
    'signal_energy': lambda x: np.sum(np.square(x)),
    'crest_factor': lambda x: np.max(np.abs(x)) / np.sqrt(np.mean(np.square(x))),
    'mean_abs': lambda x: np.mean(np.abs(x)),
    
    # Array operations
    'rolling_sum': lambda x, w: pd.Series(x).rolling(w, min_periods=1).sum().to_numpy(),
    'moving_max': lambda x, w: pd.Series(x).rolling(w, min_periods=1).max().to_numpy(),
    'moving_min': lambda x, w: pd.Series(x).rolling(w, min_periods=1).min().to_numpy(),
    'interp1': np.interp,
    'cumprod': np.cumprod,
    'scale': lambda x, factor: x * factor,
    'sign': np.sign,
    'round_to': lambda x, decimals: np.round(x, decimals),
    'modulo': np.mod,
    'where': np.where,
    'if_else': lambda condition, x, y: np.where(condition, x, y),
    
    # Logical operations
    'flag_if_above': lambda x, threshold: np.where(x > threshold, 1, 0),
    'flag_if_between': lambda x, min_val, max_val: np.where((x >= min_val) & (x <= max_val), 1, 0),
    'segment_mean': lambda segments: np.array([np.mean(seg) for seg in segments]),
    'segment_integral': lambda segments, dt: np.array([np.sum(seg) * dt for seg in segments]),
    'hold_last': lambda x: np.maximum.accumulate(x),
    'compute_rate': lambda x, dt: np.gradient(x, dt),
    'threshold_dwell': lambda x, threshold, min_duration: np.sum(x > threshold) * min_duration,
    'pulse_generator': lambda t, freq, duty: np.where(np.mod(t * freq, 1) < duty, 1, 0),
    'prev': lambda x: np.roll(x, 1),
    'next': lambda x: np.roll(x, -1),
    'running_max': np.maximum.accumulate,
    'running_min': np.minimum.accumulate,
    
    # Number system conversions
    'bin_to_dec': lambda x: int(str(x), 2),
    'bin_to_hex': lambda x: hex(int(str(x), 2)),
    'hex_to_bin': lambda x: bin(int(str(x), 16)),
    'dec_to_bin': lambda x: bin(int(x)),
    'dec_to_hex': lambda x: hex(int(x)),
    
    # Array creation and manipulation
    'array': np.array,
    'exp': np.exp,
    'min': np.min,
    'max': np.max,
    'butter': signal.butter,
    'filtfilt': signal.filtfilt,
    'lfilter': signal.lfilter,
    'fft': np.fft.fft,
    'fftfreq': np.fft.fftfreq,
    'rolling_mean': lambda x, w: pd.Series(x).rolling(w, min_periods=1).mean().to_numpy(),
    'rolling_std': lambda x, w: pd.Series(x).rolling(w, min_periods=1).std().to_numpy(),
    'rolling_max': lambda x, w: pd.Series(x).rolling(w, min_periods=1).max().to_numpy(),
    'rolling_min': lambda x, w: pd.Series(x).rolling(w, min_periods=1).min().to_numpy(),
    'derivative': lambda x, dt: np.gradient(x, dt),
    'compute_rate': lambda x, dt: np.gradient(x, dt),
    'integration': lambda x, dt: np.cumsum(x) * dt,
    'segment_integral': lambda segments, dt: np.array([np.sum(seg) * dt for seg in segments]),
    'second_derivative': lambda x, dt: np.gradient(np.gradient(x, dt), dt),
    'lookup1d': lambda x, table: np.interp(x, np.arange(len(table)), table),
    'lookup1d_safe': lambda x, table: np.interp(np.clip(x, 0, len(table)-1), np.arange(len(table)), table),
    'is_constant': lambda x: np.all(x == x[0]),
    'detect_spikes': lambda x, threshold: np.where(np.abs(np.diff(x, prepend=x[0])) > threshold, 1, 0),
    'nan_to_num': np.nan_to_num,
    'is_nan': np.isnan,
    'sort_indices': np.argsort,
    'rank': lambda x: np.argsort(np.argsort(x)),
    'moving_argmax': lambda x, w: pd.Series(x).rolling(w, min_periods=1).apply(np.argmax).to_numpy(),
    'moving_argmin': lambda x, w: pd.Series(x).rolling(w, min_periods=1).apply(np.argmin).to_numpy(),
    'time_shift': lambda x, shift: np.roll(x, shift),
    'lagged_diff': lambda x, lag: np.diff(x, prepend=x[0], n=lag),
    'delay_detector': lambda x, y: np.argmax(np.correlate(x, y, mode='full')) - len(x) + 1,
    
    # Reindexing and forward fill functions
    'reindex': lambda x, new_index: pd.Series(x).reindex(new_index).to_numpy(),
    'ffill': lambda x: pd.Series(x).ffill().to_numpy(),
    'bfill': lambda x: pd.Series(x).bfill().to_numpy(),
    'interpolate': lambda x: pd.Series(x).interpolate().to_numpy(),
    
    # Logical operations
    'logical_and': np.logical_and,
    'logical_or': np.logical_or,
    'logical_not': np.logical_not,
    'logical_xor': np.logical_xor,
    'all_true': np.all,
    'any_true': np.any,
    'in_range': lambda x, min_val, max_val: (x >= min_val) & (x <= max_val),
    'between': lambda x, min_val, max_val: (x >= min_val) & (x <= max_val),
    'equal': np.equal,
    'greater_than': np.greater,
    'less_than': np.less,
    
    # User-defined function support
    'def': lambda name, *args, **kwargs: None,  # Placeholder for function definition
    'return': lambda x: x,  # Placeholder for return statement
    'lambda': lambda x: x,  # Support for lambda functions
    
    # Time series operations
    'fillna': lambda x, value: pd.Series(x).fillna(value).to_numpy(),
    'asfreq': lambda x, freq: pd.Series(x).asfreq(freq).to_numpy(),
    'resample': lambda x, rule: pd.Series(x).resample(rule).mean().to_numpy(),
    'merge_asof': lambda x, y: pd.merge_asof(pd.Series(x), pd.Series(y)).to_numpy(),
    'merge_ordered': lambda x, y: pd.merge_ordered(pd.Series(x), pd.Series(y)).to_numpy(),
    'align': lambda x, y: pd.Series(x).align(pd.Series(y))[0].to_numpy(),
    'shift': lambda x, periods: pd.Series(x).shift(periods).to_numpy(),
    'diff': lambda x, periods: pd.Series(x).diff(periods).to_numpy(),
    'pct_change': lambda x, periods: pd.Series(x).pct_change(periods).to_numpy(),
    'rolling': lambda x, window: pd.Series(x).rolling(window).mean().to_numpy(),
    'expanding': lambda x: pd.Series(x).expanding().mean().to_numpy(),
    'ewm': lambda x, span: pd.Series(x).ewm(span=span).mean().to_numpy(),
}

# Add all pandas, numpy, scipy.signal, scipy.fft functions to safe_globals
import types
for mod, prefix in [
    (pd, 'pd'),
    (np, 'np'),
    (signal, 'signal'),
    (sp_fft, 'fft')
]:
    for name in dir(mod):
        if name.startswith('_'):
            continue
        attr = getattr(mod, name)
        if isinstance(attr, (types.FunctionType, types.BuiltinFunctionType, types.MethodType, type(np))):
            safe_globals[f'{prefix}.{name}'] = attr
        # For numpy/scipy modules, also allow direct name (e.g., 'mean')
        if isinstance(attr, (types.FunctionType, types.BuiltinFunctionType, types.MethodType)):
            safe_globals[name] = attr

# Also allow the modules themselves
safe_globals['np'] = np
safe_globals['pd'] = pd
safe_globals['signal'] = signal
safe_globals['fft'] = sp_fft

def validate_code(code):
    """Validate Python code for security and correctness"""
    try:
        # Parse the code into an AST
        tree = ast.parse(code)
        
        # Check for potentially dangerous operations
        for node in ast.walk(tree):
            # Disallow imports
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                raise ValueError("Import statements are not allowed")
            
            # Disallow class definitions
            if isinstance(node, ast.ClassDef):
                raise ValueError("Class definitions are not allowed")
            
            # Disallow global statements
            if isinstance(node, ast.Global):
                raise ValueError("Global statements are not allowed")
            
            # Disallow nonlocal statements
            if isinstance(node, ast.Nonlocal):
                raise ValueError("Nonlocal statements are not allowed")
            
            # Disallow yield statements
            if isinstance(node, ast.Yield):
                raise ValueError("Yield statements are not allowed")
            
            # Disallow yield from statements
            if isinstance(node, ast.YieldFrom):
                raise ValueError("Yield from statements are not allowed")
            
            # Disallow async/await
            if isinstance(node, (ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith, ast.Await)):
                raise ValueError("Async/await is not allowed")
            
            # Disallow exec/eval
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in ('exec', 'eval'):
                        raise ValueError("exec/eval calls are not allowed")
        
        return True
    except Exception as e:
        logger.error(f"Code validation error: {str(e)}")
        raise

def execute_derived_parameter(code, parameters):
    """
    Execute user code in a safe environment to generate a derived parameter
    
    Args:
        code (str): Python code to execute
        parameters (dict): Dictionary of parameter names and their values
    
    Returns:
        numpy.ndarray: Result of the code execution
    """
    try:
        # Validate the code
        validate_code(code)
        
        # Create a local environment with the parameters
        local_env = {name: np.array(values) for name, values in parameters.items()}
        
        # Execute the code in the safe environment
        exec(code, safe_globals, local_env)
        
        # Get the result (assuming the last expression is the result)
        result = local_env.get('result')
        if result is None:
            raise ValueError("Code must assign the result to a variable named 'result'")
        
        return result
        
    except Exception as e:
        logger.error(f"Error executing derived parameter code: {str(e)}")
        raise 