import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import os
import traceback
from .db import save_timeseries_data
from .db import set_global_time

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def sanitize_parameter_name(param_name):
    """
    파라미터 이름에서 dash(-)를 언더바(_)로 치환합니다.
    
    Parameters:
    -----------
    param_name : str
        원본 파라미터 이름
    
    Returns:
    --------
    str
        치환된 파라미터 이름
    """
    sanitized_name = param_name.replace('-', '_')
    logger.info(f"Parameter name sanitized: '{param_name}' -> '{sanitized_name}'")
    return sanitized_name

def parse_time(time_str):
    """
    Parse time string in format 'DDD:HH:MM:SS.mmmUUU' to total seconds
    """
    try:
        # Handle NaN and invalid values
        if pd.isna(time_str) or str(time_str).lower() in ['nan', 'none', '']:
            logger.warning(f"Skipping invalid time value: {time_str}")
            return None
        
        time_str = str(time_str).strip()
        if not time_str:
            logger.warning(f"Skipping empty time value")
            return None
        
        # Handle both formats: 'DDD HH:MM:SS.mmmUUU' and 'DDD:HH:MM:SS.mmmUUU'
        if ' ' in time_str:
            # Original format: 'DDD HH:MM:SS.mmmUUU'
            date_part, time_part = time_str.split()
        else:
            # Fixed-wing format: 'DDD:HH:MM:SS.mmmUUU'
            # Split by first colon to separate day and time
            parts = time_str.split(':', 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid time format: {time_str}")
            date_part, time_part = parts[0], parts[1]
        
        # Convert day of year to total days
        day_of_year = int(date_part)
        total_days = day_of_year - 1  # 0-based day count
        
        # Parse time part (HH:MM:SS.mmmUUU)
        time_parts = time_part.split('.')
        base_time = datetime.strptime(time_parts[0], '%H:%M:%S')
        
        # Calculate total seconds
        total_seconds = (
            total_days * 24 * 3600 +  # days to seconds
            base_time.hour * 3600 +   # hours to seconds
            base_time.minute * 60 +   # minutes to seconds
            base_time.second          # seconds
        )
        
        # Add microseconds if present (no dot separator in microseconds)
        if len(time_parts) > 1:
            microseconds = int(time_parts[1].ljust(6, '0')[:6])
            total_seconds += microseconds / 1_000_000
            
        return total_seconds
    except Exception as e:
        logger.error(f"Error parsing time string {time_str}: {str(e)}")
        return None

def process_csv_file(filepath, file_type='regular'):
    """
    Process CSV file by reading in chunks to handle massive files.
    Splits parameters larger than CHUNK_SIZE points into separate DB entries.
    """
    CHUNK_SIZE = 50_000_000
    try:
        logger.info(f"Processing CSV file: {filepath} (type: {file_type})")

        # --- Pass 1: Determine global start time efficiently ---
        header_df = pd.read_csv(filepath, nrows=0, encoding='utf-8')
        all_columns = [col for col in header_df.columns if not col.startswith('Unnamed')]
        if len(all_columns) < 2:
            raise ValueError("CSV must have at least a time and a data column.")
        time_col = all_columns[0]
        
        time_iterator = pd.read_csv(filepath, usecols=[time_col], chunksize=1_000_000, na_values=['', 'nan', 'NaN'], encoding='utf-8')
        global_start_time = float('inf')
        max_end_time = float('-inf')

        for i, chunk in enumerate(time_iterator):
            if file_type == 'fixed_wing' and i == 0:
                chunk = chunk.iloc[2:] # Skip header rows for fixed-wing
            
            valid_times = chunk[time_col].apply(parse_time).dropna()
            if not valid_times.empty:
                min_in_chunk = valid_times.min()
                max_in_chunk = valid_times.max()
                if min_in_chunk < global_start_time:
                    global_start_time = min_in_chunk
                if max_in_chunk > max_end_time:
                    max_end_time = max_in_chunk
        
        if global_start_time == float('inf'):
            raise ValueError("No valid time data found.")

        set_global_time(global_start_time, max_end_time)
        logger.info(f"Global time determined: {global_start_time} to {max_end_time}")

        # --- Pass 2: Process each data column, splitting if necessary ---
        data_cols = all_columns[1:]
        for data_col in data_cols:
            param_name = sanitize_parameter_name(data_col)
            logger.info(f"Processing column: {param_name}")
            try:
                iterator = pd.read_csv(filepath, usecols=[time_col, data_col], chunksize=CHUNK_SIZE, na_values=['', 'nan', 'NaN'], encoding='utf-8')
                
                first_chunk = next(iterator, None)
                if first_chunk is None:
                    logger.warning(f"Column {data_col} is empty. Skipping.")
                    continue

                second_chunk = next(iterator, None)

                if second_chunk is None:
                    # Single chunk, save without suffix
                    logger.info(f"Parameter {param_name} fits in a single chunk.")
                    if file_type == 'fixed_wing':
                        first_chunk = first_chunk.iloc[2:]
                    
                    time_series = first_chunk[time_col].apply(parse_time)
                    value_series = pd.to_numeric(first_chunk[data_col], errors='coerce')
                    mask = time_series.notna() & value_series.notna()
                    
                    relative_time = time_series[mask].to_numpy(dtype=np.float64) - global_start_time
                    value_data = value_series[mask].to_numpy(dtype=np.float64)

                    if relative_time.size > 0:
                        save_timeseries_data(param_name, relative_time, value_data, 0)
                else:
                    # Multiple chunks, needs splitting
                    logger.info(f"Parameter {param_name} exceeds {CHUNK_SIZE} rows. Splitting.")
                    # Process first chunk
                    chunk_param_name = f"{param_name}_1"
                    logger.info(f"Processing chunk 1 -> {chunk_param_name}")
                    if file_type == 'fixed_wing':
                        first_chunk = first_chunk.iloc[2:]

                    time_series = first_chunk[time_col].apply(parse_time)
                    value_series = pd.to_numeric(first_chunk[data_col], errors='coerce')
                    mask = time_series.notna() & value_series.notna()
                    relative_time = time_series[mask].to_numpy(dtype=np.float64) - global_start_time
                    value_data = value_series[mask].to_numpy(dtype=np.float64)
                    if relative_time.size > 0:
                        save_timeseries_data(chunk_param_name, relative_time, value_data, 0)

                    # Process second chunk
                    chunk_param_name = f"{param_name}_2"
                    logger.info(f"Processing chunk 2 -> {chunk_param_name}")
                    time_series = second_chunk[time_col].apply(parse_time)
                    value_series = pd.to_numeric(second_chunk[data_col], errors='coerce')
                    mask = time_series.notna() & value_series.notna()
                    relative_time = time_series[mask].to_numpy(dtype=np.float64) - global_start_time
                    value_data = value_series[mask].to_numpy(dtype=np.float64)
                    if relative_time.size > 0:
                        save_timeseries_data(chunk_param_name, relative_time, value_data, 0)

                    # Process remaining chunks
                    for i, chunk_df in enumerate(iterator, start=3):
                        chunk_param_name = f"{param_name}_{i}"
                        logger.info(f"Processing chunk {i} -> {chunk_param_name}")
                        time_series = chunk_df[time_col].apply(parse_time)
                        value_series = pd.to_numeric(chunk_df[data_col], errors='coerce')
                        mask = time_series.notna() & value_series.notna()
                        relative_time = time_series[mask].to_numpy(dtype=np.float64) - global_start_time
                        value_data = value_series[mask].to_numpy(dtype=np.float64)
                        if relative_time.size > 0:
                            save_timeseries_data(chunk_param_name, relative_time, value_data, 0)

            except Exception as e:
                logger.error(f"Error processing column {data_col}: {e}")
                continue

    except Exception as e:
        logger.error(f"Error processing CSV file: {str(e)}")
        logger.error(traceback.format_exc())
        raise Exception(f"Error processing CSV file: {str(e)}")
    finally:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Cleaned up uploaded CSV file: {filepath}")
        except Exception as e:
            logger.warning(f"Failed to clean up uploaded file: {str(e)}") 