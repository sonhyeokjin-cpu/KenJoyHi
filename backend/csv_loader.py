import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import os
import traceback
from .db import set_global_time, DB_PATH
from .storage import channel_writers

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

def parse_time_series(series):
    """Vectorized DDD HH:MM:SS.ffffff / DDD:HH:MM:SS.ffffff parser."""
    text = series.astype('string').str.strip()
    parts = text.str.extract(
        r'^(?P<day>\d{1,3})(?:\s+|:)(?P<hour>\d{1,2}):'
        r'(?P<minute>\d{2}):(?P<second>\d{2})(?:\.(?P<fraction>\d+))?$'
    )
    day = pd.to_numeric(parts['day'], errors='coerce')
    hour = pd.to_numeric(parts['hour'], errors='coerce')
    minute = pd.to_numeric(parts['minute'], errors='coerce')
    second = pd.to_numeric(parts['second'], errors='coerce')
    fraction_text = parts['fraction'].fillna('').str.slice(0, 6).str.pad(6, side='right', fillchar='0')
    microseconds = pd.to_numeric(fraction_text, errors='coerce').fillna(0)

    valid = (day.between(1, 366) & hour.between(0, 23) &
             minute.between(0, 59) & second.between(0, 59))
    result = ((day - 1) * 86400 + hour * 3600 + minute * 60 + second +
              microseconds / 1_000_000)
    return result.where(valid).astype('float64')


def process_csv_file(filepath, file_type='regular'):
    """Stream a wide CSV into SQLite using two physical file scans."""
    try:
        logger.info(f"Processing CSV file: {filepath} (type: {file_type})")

        header_df = pd.read_csv(filepath, nrows=0, encoding='utf-8')
        all_columns = [col for col in header_df.columns if not col.startswith('Unnamed')]
        if len(all_columns) < 2:
            raise ValueError("CSV must have at least a time and a data column.")
        time_col = all_columns[0]
        data_cols = all_columns[1:]
        parameter_names = [sanitize_parameter_name(column) for column in data_cols]
        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("CSV parameter names are duplicated after '-' is converted to '_'.")

        # Pass 1 reads only the time column to establish the absolute dataset range.
        time_iterator = pd.read_csv(
            filepath, usecols=[time_col], chunksize=1_000_000,
            na_values=['', 'nan', 'NaN'], encoding='utf-8'
        )
        global_start_time = float('inf')
        max_end_time = float('-inf')
        for chunk_index, chunk in enumerate(time_iterator):
            if file_type == 'fixed_wing' and chunk_index == 0:
                chunk = chunk.iloc[2:]
            valid_times = parse_time_series(chunk[time_col]).dropna()
            if not valid_times.empty:
                global_start_time = min(global_start_time, float(valid_times.min()))
                max_end_time = max(max_end_time, float(valid_times.max()))

        if global_start_time == float('inf'):
            raise ValueError("No valid time data found.")

        set_global_time(global_start_time, max_end_time,
                        time_basis='day_of_year_seconds')
        logger.info(f"Global time determined: {global_start_time} to {max_end_time}")

        # Pass 2 reads every data column together. Limit cells per chunk so wide
        # CSV files stay memory-bounded while the physical file is scanned once.
        target_cells = 2_000_000
        chunk_rows = max(10_000, min(250_000, target_cells // len(all_columns)))
        logger.info(
            f"Streaming {len(data_cols)} CSV channels in one pass "
            f"({chunk_rows} rows per chunk)."
        )
        iterator = pd.read_csv(
            filepath, usecols=all_columns, chunksize=chunk_rows,
            na_values=['', 'nan', 'NaN'], encoding='utf-8'
        )

        with channel_writers(DB_PATH, parameter_names) as writers:
            for chunk_index, chunk_df in enumerate(iterator):
                if file_type == 'fixed_wing' and chunk_index == 0:
                    chunk_df = chunk_df.iloc[2:]
                if chunk_df.empty:
                    continue

                time_series = parse_time_series(chunk_df[time_col])
                mask = time_series.notna()
                if not mask.any():
                    continue
                relative_time = (
                    time_series[mask].to_numpy(dtype=np.float64) - global_start_time
                )

                for data_col, parameter_name in zip(data_cols, parameter_names):
                    value_data = pd.to_numeric(
                        chunk_df.loc[mask, data_col], errors='coerce'
                    ).to_numpy(dtype=np.float64)
                    writers[parameter_name].append(relative_time, value_data)

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
