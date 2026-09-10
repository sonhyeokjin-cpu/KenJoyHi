import scipy.io as sio
import h5py
import numpy as np
from .db import save_timeseries_data, DB_PATH
from .storage import channel_writer
import logging
import os
import traceback
import stat
from .csv_loader import process_csv_file, sanitize_parameter_name
from .db import set_global_time

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _h5_flat_slice(dataset, start, end):
    """Read a MATLAB HDF5 vector slice without assuming (N,1) layout."""
    shape = dataset.shape
    if len(shape) == 1:
        return np.asarray(dataset[start:end]).reshape(-1)
    if len(shape) == 2 and shape[0] == 1:
        return np.asarray(dataset[:, start:end]).reshape(-1)
    if len(shape) == 2 and shape[1] == 1:
        return np.asarray(dataset[start:end, :]).reshape(-1)
    raise ValueError(f"Expected a vector dataset, got shape {shape}")

def process_file(filepath, file_type='regular'):
    """
    Process file and store data in SQLite database
    Supports both .mat and .csv files
    file_type: 'regular' or 'fixed_wing' to handle different naming conventions
    """
    try:
        logger.info(f"Processing file: {filepath} with type: {file_type}")
        
        # Check if file exists
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
            
        # Check file size
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            raise ValueError("File is empty")
            
        logger.info(f"File size: {file_size} bytes")
        
        # Determine file type and process accordingly
        file_ext = os.path.splitext(filepath)[1].lower()
        
        if file_ext == '.csv':
            process_csv_file(filepath, file_type)
        elif file_ext in ['.mat', '.matlab']:
            process_matlab_file(filepath, file_type)
        else:
            raise ValueError(f"Unsupported file format: {file_ext}")
            
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        logger.error(traceback.format_exc())
        raise Exception(f"Error processing file: {str(e)}")

def process_matlab_file(filepath, file_type):
    """
    Process MATLAB file and store data in SQLite database
    """
    try:
        logger.info(f"Processing MATLAB file: {filepath}")
        # Check if file exists
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
            
        # Check file size
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            raise ValueError("File is empty")
            
        logger.info(f"File size: {file_size} bytes")
        
        # 파일에 읽기 권한 추가
        os.chmod(filepath, stat.S_IREAD)
        
        # Try loading with scipy.io first (for v7.2 and below)
        try:
            logger.info("Attempting to load with scipy.io (v7.2 and below)")
            mat_data = sio.loadmat(filepath)
            logger.info(f"Successfully loaded with scipy.io. Keys found: {list(mat_data.keys())}")
            process_matlab_v7(mat_data, file_type)
        except NotImplementedError:
            # If scipy.io fails, try h5py (for v7.3 and above)
            logger.info("Attempting to load with h5py (v7.3 and above)")
            try:
                with h5py.File(filepath, 'r') as f:
                    logger.info(f"Successfully loaded with h5py. Keys found: {list(f.keys())}")
                    process_matlab_v73(f, file_type)
            except Exception as e:
                logger.error(f"Error loading with h5py: {str(e)}")
                logger.error(traceback.format_exc())
                raise Exception(f"Failed to load MATLAB file with both scipy.io and h5py: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing MATLAB file: {str(e)}")
        logger.error(traceback.format_exc())
        raise Exception(f"Error processing MATLAB file: {str(e)}")
    finally:
        # Clean up uploaded file
        try:
            if os.path.exists(filepath):
                os.chmod(filepath, stat.S_IWRITE | stat.S_IREAD)
                os.remove(filepath)
                logger.info(f"Cleaned up uploaded file: {filepath}")
        except Exception as e:
            logger.warning(f"Failed to clean up uploaded file: {str(e)}")
            logger.warning(traceback.format_exc())

def process_matlab_v7(mat_data, file_type='regular'):
    """
    Process MATLAB v7.2 and below format
    """
    logger.info(f"Processing MATLAB v7.2 format with file_type: {file_type}")
    
    # Choose variable naming convention based on file type
    if file_type == 'fixed_wing':
        time_suffix = '_X'
        data_suffix = '_Y'
        time_divisor = 1_000_000.0  # Fixed-wing uses microseconds (epoch microtime)
        logger.info("Using Fixed-wing naming convention: _X for time, _Y for data, microseconds (epoch microtime)")
    else:
        time_suffix = '_time'
        data_suffix = '_data'
        time_divisor = 1_000_000.0  # Regular files also use microseconds (epoch microtime)
        logger.info("Using regular naming convention: _time for time, _data for data, microseconds (epoch microtime)")
    
    time_vars = [key for key in mat_data.keys() if key.endswith(time_suffix) and not key.startswith('__')]
    logger.info(f"Found time variables: {time_vars}")
    if not time_vars:
        raise ValueError(f"No time variables found in MATLAB file (looking for *{time_suffix})")

    # 모든 파라미터의 첫/마지막 타임스탬프만 모아서 global_time 계산
    first_times = []
    last_times = []
    for time_var in time_vars:
        time_data = mat_data[time_var].flatten()
        if len(time_data) > 0:
            first_times.append(time_data[0])
            last_times.append(time_data[-1])
    if not first_times or not last_times:
        raise ValueError("No valid time data found in MATLAB file")
    
    # 시간 단위 변환 전 원본 값 로깅
    print(f"[DEBUG] Original first_times: {first_times}")
    print(f"[DEBUG] Original last_times: {last_times}")
    print(f"[DEBUG] Time divisor: {time_divisor}")
    
    # Global time 계산 및 검증
    min_first_time = min(first_times)
    max_last_time = max(last_times)
    
    # 시간 단위 변환
    global_start_seconds = float(min_first_time) / time_divisor
    global_end_seconds = float(max_last_time) / time_divisor
    
    print(f"[DEBUG] Converted global time: {global_start_seconds} to {global_end_seconds} seconds")
    
    # 시간 값 검증
    if global_start_seconds < 0 or global_end_seconds < 0:
        logger.warning(f"Negative time values detected: start={global_start_seconds}, end={global_end_seconds}")
    if global_start_seconds >= global_end_seconds:
        logger.warning(f"Invalid time range: start={global_start_seconds}, end={global_end_seconds}")
    
    set_global_time(global_start_seconds, global_end_seconds,
                    time_basis='epoch_microseconds')

    global_start_time = min(first_times)
    for time_var in time_vars:
        param_name = time_var[:-len(time_suffix)]  # Remove time suffix
        param_name = sanitize_parameter_name(param_name)  # Sanitize parameter name
        data_var = time_var[:-len(time_suffix)] + data_suffix  # Use data suffix for data lookup
        if data_var in mat_data:
            logger.info(f"Processing time series: {param_name}")
            time_data = mat_data[time_var].flatten()  # Ensure 1D array
            value_data = mat_data[data_var].flatten()  # Ensure 1D array
            logger.info(f"Time data shape: {time_data.shape}, Value data shape: {value_data.shape}")
            logger.info(f"Time data sample: {time_data[:5]}")
            logger.info(f"Value data sample: {value_data[:5]}")
            logger.info(f"Original data statistics before saving:")
            logger.info(f"  Time array: min={np.min(time_data)}, max={np.max(time_data)}, len={len(time_data)}")
            logger.info(f"  Value array: min={np.min(value_data)}, max={np.max(value_data)}, mean={np.mean(value_data):.6f}, std={np.std(value_data):.6f}")
            try:
                logger.info(f"Saving original data for {param_name} (length: {len(time_data)})")
                relative_time = (time_data - global_start_time) / time_divisor
                save_timeseries_data(param_name, relative_time, value_data, 0)
            except Exception as e:
                logger.error(f"Error saving data for {param_name}: {str(e)}")
                logger.error(traceback.format_exc())
                raise
        else:
            logger.warning(f"No matching data variable found for {param_name} (looking for {data_var})")

def process_matlab_v73(h5_data, file_type='regular'):
    """
    Process MATLAB v7.3 and above format, chunking large variables.
    """
    logger.info(f"Processing MATLAB v7.3 format with file_type: {file_type}")
    CHUNK_SIZE = 250_000

    if file_type == 'fixed_wing':
        time_suffix, data_suffix, time_divisor = '_X', '_Y', 1_000_000.0
        logger.info("Using Fixed-wing naming convention for v7.3")
    else:
        time_suffix, data_suffix, time_divisor = '_time', '_data', 1_000_000.0
        logger.info("Using regular naming convention for v7.3")

    time_vars = [key for key in h5_data.keys() if key.endswith(time_suffix) and not key.startswith('__')]
    if not time_vars:
        raise ValueError(f"No time variables found in MATLAB v7.3 file (looking for *{time_suffix})")

    # Pass 1: Determine global start time from all time variables
    global_start_time = float('inf')
    max_end_time = float('-inf')
    for time_var in time_vars:
        time_dataset = h5_data[time_var]
        if time_dataset.size > 0:
            # Read only first and last element to find min/max
            first_val = _h5_flat_slice(time_dataset, 0, 1)[0]
            last_val = _h5_flat_slice(time_dataset, time_dataset.size - 1, time_dataset.size)[-1]
            if first_val < global_start_time:
                global_start_time = first_val
            if last_val > max_end_time:
                max_end_time = last_val

    if global_start_time == float('inf'):
        raise ValueError("Could not determine a global start time.")

    set_global_time(global_start_time / time_divisor, max_end_time / time_divisor,
                    time_basis='epoch_microseconds')
    logger.info(f"Global time determined for v7.3: {global_start_time} to {max_end_time}")

    # Pass 2: Process each variable, chunking if necessary
    for time_var in time_vars:
        param_name = sanitize_parameter_name(time_var[:-len(time_suffix)])
        data_var = time_var[:-len(time_suffix)] + data_suffix
        
        if data_var in h5_data:
            logger.info(f"Processing parameter: {param_name}")
            time_dataset = h5_data[time_var]
            value_dataset = h5_data[data_var]
            total_points = int(time_dataset.size)

            try:
                logger.info(f"Streaming {param_name} ({total_points} points) in {CHUNK_SIZE}-sample chunks.")
                with channel_writer(DB_PATH, param_name) as writer:
                    for start_idx in range(0, total_points, CHUNK_SIZE):
                        end_idx = min(start_idx + CHUNK_SIZE, total_points)
                        time_chunk = _h5_flat_slice(time_dataset, start_idx, end_idx)
                        value_chunk = _h5_flat_slice(value_dataset, start_idx, end_idx)
                        if time_chunk.size != value_chunk.size:
                            raise ValueError(f"{param_name}: time/value lengths differ")
                        relative_time = (time_chunk - global_start_time) / time_divisor
                        writer.append(relative_time, value_chunk)
            except Exception as e:
                logger.error(f"Failed to process parameter {param_name}: {e}")
                logger.error(traceback.format_exc())
                continue # Skip to next parameter
        else:
            logger.warning(f"No matching data variable found for {param_name} (looking for {data_var})") 
