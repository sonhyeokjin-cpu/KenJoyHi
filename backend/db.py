import sqlite3
import numpy as np
import os
import logging
import atexit
import sys
import traceback
import stat

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 실행 파일 기준 상대 경로로 DB 경로 설정
if getattr(sys, 'frozen', False):
    # PyInstaller로 패키징된 경우
    # 임시 폴더를 사용 (templates, static 등이 포함된 곳)
    application_path = sys._MEIPASS
    # 데이터 저장용 경로는 실행 파일 폴더 사용
    data_path = os.path.dirname(sys.executable)
else:
    # 일반 Python 실행의 경우
    application_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_path = application_path

DB_PATH = os.path.join(data_path, 'data', 'timeseries.db')
logger.info(f"Database path set to: {DB_PATH}")

# 데이터베이스 초기화 상태 추적
_db_initialized = False

def ensure_data_directory():
    """데이터 디렉토리가 존재하는지 확인하고 생성"""
    try:
        data_dir = os.path.dirname(DB_PATH)
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            logger.info(f"Created data directory at {data_dir}")
        
        # 쓰기 권한 확인 및 설정
        if not os.access(data_dir, os.W_OK):
            os.chmod(data_dir, stat.S_IWRITE | stat.S_IEXEC | stat.S_IREAD)
            logger.info(f"Added write permissions to data directory: {data_dir}")
        
        # 테스트 파일로 쓰기 권한 확인
        test_file = os.path.join(data_dir, '.test_write')
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            logger.info(f"Write permission test successful for data directory")
        except Exception as e:
            logger.error(f"Write permission test failed for data directory: {str(e)}")
            raise Exception(f"No write permission for data directory: {data_dir}")
            
        return True
    except Exception as e:
        logger.error(f"Error creating data directory: {str(e)}")
        logger.error(traceback.format_exc())
        return False

def cleanup_database():
    """
    프로그램 종료 시 데이터베이스 파일 삭제
    """
    global _db_initialized
    if not _db_initialized:
        logger.info("Database was not initialized, skipping cleanup")
        return
        
    try:
        if os.path.exists(DB_PATH):
            # 파일에 쓰기 권한 추가
            os.chmod(DB_PATH, stat.S_IWRITE | stat.S_IREAD)
            os.remove(DB_PATH)
            logger.info("Database file removed successfully")
    except Exception as e:
        logger.error(f"Error removing database file: {str(e)}")
        logger.error(traceback.format_exc())

def init_db():
    """
    Initialize the SQLite database
    """
    global _db_initialized
    conn = None
    try:
        logger.info(f"Initializing database at {DB_PATH}")
        
        # Ensure data directory exists with proper permissions
        if not ensure_data_directory():
            raise Exception("Failed to create data directory")
        
        # Delete existing database file if it exists
        if os.path.exists(DB_PATH):
            try:
                os.chmod(DB_PATH, stat.S_IWRITE | stat.S_IREAD)
                os.remove(DB_PATH)
                logger.info("Existing database file removed")
            except Exception as e:
                logger.error(f"Error removing existing database file: {str(e)}")
                logger.error(traceback.format_exc())
                raise
        
        # 데이터베이스 연결
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Create tables
        try:
            # Create parameters table
            c.execute('''
                CREATE TABLE IF NOT EXISTS parameters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                )
            ''')
            logger.info("Created parameters table")
            
            # Create timeseries table
            c.execute('''
                CREATE TABLE IF NOT EXISTS timeseries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parameter_id INTEGER,
                    level INTEGER,
                    time_data BLOB,
                    value_data BLOB,
                    FOREIGN KEY (parameter_id) REFERENCES parameters (id)
                )
            ''')
            logger.info("Created timeseries table")
            
            # Create global_time table
            c.execute('''
                CREATE TABLE IF NOT EXISTS global_time (
                    id INTEGER PRIMARY KEY,
                    start_time REAL,
                    end_time REAL
                )
            ''')
            logger.info("Created global_time table")
            
            # Create time_segments table
            c.execute('''
                CREATE TABLE IF NOT EXISTS time_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    start REAL NOT NULL,
                    end REAL NOT NULL
                )
            ''')
            logger.info("Created time_segments table")
            
            # Create chart_layout table for storing chart information
            c.execute('''
                CREATE TABLE IF NOT EXISTS chart_layout (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chart_id TEXT NOT NULL,
                    chart_order INTEGER NOT NULL,
                    parameters TEXT,  -- JSON string of parameter names
                    scale_info TEXT,  -- JSON string of scale information
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logger.info("Created chart_layout table")
            
            # Verify tables were created
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = c.fetchall()
            table_names = [table[0] for table in tables]
            logger.info(f"Created tables: {table_names}")
            
            if 'parameters' not in table_names or 'timeseries' not in table_names:
                raise Exception("Failed to create required tables")
            
            conn.commit()
            _db_initialized = True
            logger.info("Database initialization completed successfully")
            
        except Exception as e:
            logger.error(f"Error creating tables: {str(e)}")
            logger.error(traceback.format_exc())
            conn.rollback()
            raise
        
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        logger.error(traceback.format_exc())
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

def ensure_tables_exist(cursor):
    """
    Ensure that required tables exist in the database
    """
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        table_names = [table[0] for table in tables]
        
        if 'parameters' not in table_names or 'timeseries' not in table_names:
            logger.info("Creating missing tables...")
            
            # Create parameters table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS parameters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                )
            ''')
            
            # Create timeseries table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS timeseries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parameter_id INTEGER,
                    level INTEGER,
                    time_data BLOB,
                    value_data BLOB,
                    FOREIGN KEY (parameter_id) REFERENCES parameters (id)
                )
            ''')
            
            # Create time_segments table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS time_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    start REAL NOT NULL,
                    end REAL NOT NULL
                )
            ''')
            
            logger.info("Tables created successfully")
            return True
            
        return True
    except Exception as e:
        logger.error(f"Error ensuring tables exist: {str(e)}")
        logger.error(traceback.format_exc())
        return False

def save_timeseries_data(param_name, time_data, value_data, level):
    """
    Save time series data to the database
    """
    logger.info(f"Saving timeseries data for {param_name} (level {level})")
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Ensure tables exist
        if not ensure_tables_exist(c):
            raise Exception("Failed to ensure tables exist")
        
        # Insert or get parameter ID
        c.execute('INSERT OR IGNORE INTO parameters (name) VALUES (?)', (param_name,))
        c.execute('SELECT id FROM parameters WHERE name = ?', (param_name,))
        param_id = c.fetchone()[0]
        logger.info(f"Parameter ID for {param_name}: {param_id}")
        
        # Convert input data to numpy arrays if they are not already
        if not isinstance(time_data, np.ndarray):
            time_data = np.array(time_data, dtype=np.float64)
        if not isinstance(value_data, np.ndarray):
            value_data = np.array(value_data, dtype=np.float64)
        
        # Convert numpy arrays to bytes
        time_blob = time_data.tobytes()
        value_blob = value_data.tobytes()
        
        # Save time series data
        c.execute('''
            INSERT INTO timeseries (parameter_id, level, time_data, value_data)
            VALUES (?, ?, ?, ?)
        ''', (param_id, level, time_blob, value_blob))
        
        conn.commit()
        logger.info(f"Successfully saved timeseries data for {param_name} (level {level})")
    except Exception as e:
        logger.error(f"Error saving timeseries data: {str(e)}")
        logger.error(traceback.format_exc())
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

def get_parameters():
    """
    Get list of all parameters
    """
    logger.info("Fetching parameters list")
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Ensure tables exist
        if not ensure_tables_exist(c):
            raise Exception("Failed to ensure tables exist")
        
        # Get all parameters
        c.execute('SELECT name FROM parameters')
        parameters = [row[0] for row in c.fetchall()]
        
        # Log the actual SQL query and results
        logger.info(f"SQL Query: SELECT name FROM parameters")
        logger.info(f"Found {len(parameters)} parameters: {parameters}")
        
        return parameters
    except Exception as e:
        logger.error(f"Error fetching parameters: {str(e)}")
        logger.error(traceback.format_exc())
        raise
    finally:
        if conn:
            conn.close()

def downsample_data(time_data, value_data, resolution):
    """
    Downsample time series data using a min/max approach for visualization.
    """
    if resolution is None or len(time_data) <= resolution:
        return time_data, value_data

    n = len(time_data)
    bucket_size = n / resolution
    
    out_time = []
    out_value = []

    for i in range(resolution):
        start_idx = int(i * bucket_size)
        end_idx = int((i + 1) * bucket_size)
        if start_idx >= n:
            break
        
        bucket = value_data[start_idx:end_idx]
        if len(bucket) == 0:
            continue

        min_val_idx = np.argmin(bucket)
        max_val_idx = np.argmax(bucket)
        
        # Get original indices
        min_orig_idx = start_idx + min_val_idx
        max_orig_idx = start_idx + max_val_idx

        # Add points in chronological order
        if min_orig_idx < max_orig_idx:
            out_time.append(time_data[min_orig_idx])
            out_value.append(value_data[min_orig_idx])
            out_time.append(time_data[max_orig_idx])
            out_value.append(value_data[max_orig_idx])
        elif max_orig_idx < min_orig_idx:
            out_time.append(time_data[max_orig_idx])
            out_value.append(value_data[max_orig_idx])
            out_time.append(time_data[min_orig_idx])
            out_value.append(value_data[min_orig_idx])
        else: # min and max are the same point
            out_time.append(time_data[min_orig_idx])
            out_value.append(value_data[min_orig_idx])

    return np.array(out_time), np.array(out_value)

def get_timeseries_data(parameter, start, end, resolution=None, file_type=None):
    """
    Get time series data for a parameter within the specified time range.
    Downsampling is applied if the parameter's total points > 10M AND the points in the current view > 2M.
    """
    logger.info(f"Getting timeseries data for {parameter} from {start} to {end} with resolution {resolution}")
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute('SELECT id FROM parameters WHERE name = ?', (parameter,))
        result = c.fetchone()
        if not result:
            logger.error(f"Parameter {parameter} not found")
            return {'time': [], 'value': []}
        
        param_id = result[0]
        
        query = "SELECT time_data, value_data FROM timeseries WHERE parameter_id = ? AND level = 0 ORDER BY id DESC LIMIT 1"
        c.execute(query, (param_id,))
        result = c.fetchone()
        
        if not result:
            logger.error(f"No data found for parameter {parameter}")
            return {'time': [], 'value': []}
        
        time_blob, value_blob = result
        full_time_data = np.frombuffer(time_blob, dtype=np.float64)
        full_value_data = np.frombuffer(value_blob, dtype=np.float64)

        total_points = len(full_time_data)

        # Filter by time range first
        if start != -float('inf') or end != float('inf'):
            mask = (full_time_data >= start) & (full_time_data <= end)
            time_data = full_time_data[mask]
            value_data = full_value_data[mask]
        else:
            time_data = full_time_data
            value_data = full_value_data

        # Then, filter out any NaN values
        valid_mask = ~np.isnan(value_data)
        time_data = time_data[valid_mask]
        value_data = value_data[valid_mask]

        num_view_points = len(time_data)
        logger.info(f"Total points for {parameter} is {total_points}. Points in view [{start}, {end}] is {num_view_points}.")

        logger.info("Returning raw data for the requested range without downsampling.")

        if len(time_data) > 0:
            logger.info(f"  Returning Time array: min={np.min(time_data)}, max={np.max(time_data)}, len={len(time_data)}")
            logger.info(f"  Returning Value array: min={np.min(value_data)}, max={np.max(value_data)}, mean={np.mean(value_data):.6f}")
        
        return {
            'time': time_data.tolist(),
            'value': value_data.tolist()
        }
        
    except Exception as e:
        logger.error(f"Error getting timeseries data: {str(e)}")
        logger.error(traceback.format_exc())
        raise
    finally:
        if conn:
            conn.close()

def debug_database():
    """
    Debug function to print database contents
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Check tables
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = c.fetchall()
        logger.info(f"Database tables: {tables}")
        
        # Check parameters
        c.execute("SELECT * FROM parameters")
        parameters = c.fetchall()
        logger.info(f"Parameters table contents: {parameters}")
        
        # Check timeseries
        c.execute("SELECT parameter_id, level, COUNT(*) FROM timeseries GROUP BY parameter_id, level")
        timeseries = c.fetchall()
        logger.info(f"Timeseries table contents: {timeseries}")
        
    except Exception as e:
        logger.error(f"Error debugging database: {str(e)}")
        logger.error(traceback.format_exc())
    finally:
        if conn:
            conn.close()

def get_global_start_time():
    """
    DB에 저장된 모든 파라미터의 첫 시간값 중 최소값(전체 기준 시작시점, 초 단위)을 반환
    """
    logger.info("Fetching global start time (minimum of all parameter first times)")
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Ensure tables exist
        if not ensure_tables_exist(c):
            raise Exception("Failed to ensure tables exist")
        # Get all parameter IDs
        c.execute('SELECT id FROM parameters')
        param_ids = [row[0] for row in c.fetchall()]
        first_times = []
        for param_id in param_ids:
            c.execute('''
                SELECT time_data FROM timeseries
                WHERE parameter_id = ? AND level = 0
                ORDER BY id DESC
                LIMIT 1
            ''', (param_id,))
            result = c.fetchone()
            if result:
                time_blob = result[0]
                time_data = np.frombuffer(time_blob, dtype=np.float64)
                if len(time_data) > 0:
                    first_times.append(time_data[0])
        if not first_times:
            logger.warning("No valid time data found in database")
            return 0.0
        global_start_time = min(first_times)
        logger.info(f"Global start time: {global_start_time}")
        return global_start_time
    except Exception as e:
        logger.error(f"Error fetching global start time: {str(e)}")
        logger.error(traceback.format_exc())
        raise
    finally:
        if conn:
            conn.close()

def get_global_end_time():
    """
    DB에 저장된 모든 파라미터의 마지막 시간값 중 최대값(전체 기준 종료시점, 초 단위)을 반환
    """
    logger.info("Fetching global end time (maximum of all parameter last times)")
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Ensure tables exist
        if not ensure_tables_exist(c):
            raise Exception("Failed to ensure tables exist")
        # Get all parameter IDs
        c.execute('SELECT id FROM parameters')
        param_ids = [row[0] for row in c.fetchall()]
        last_times = []
        for param_id in param_ids:
            c.execute('''
                SELECT time_data FROM timeseries
                WHERE parameter_id = ? AND level = 0
                ORDER BY id DESC
                LIMIT 1
            ''', (param_id,))
            result = c.fetchone()
            if result:
                time_blob = result[0]
                time_data = np.frombuffer(time_blob, dtype=np.float64)
                if len(time_data) > 0:
                    last_times.append(time_data[-1])
        if not last_times:
            logger.warning("No valid time data found in database")
            return 0.0
        global_end_time = max(last_times)
        logger.info(f"Global end time: {global_end_time}")
        return global_end_time
    except Exception as e:
        logger.error(f"Error fetching global end time: {str(e)}")
        logger.error(traceback.format_exc())
        raise
    finally:
        if conn:
            conn.close()

def ensure_global_time_table():
    """global_time 테이블이 없으면 생성"""
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS global_time (
                id INTEGER PRIMARY KEY,
                start_time REAL,
                end_time REAL
            )
        ''')
        conn.commit()
    finally:
        conn.close()

def set_global_time(start, end):
    ensure_global_time_table()
    print(f"[DEBUG][set_global_time] DB_PATH: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO global_time (id, start_time, end_time)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET start_time=excluded.start_time, end_time=excluded.end_time
        ''', (start, end))
        conn.commit()
        print(f"[DEBUG][set_global_time] committed start={start}, end={end}")
        # 바로 읽어서 확인
        c.execute('SELECT start_time, end_time FROM global_time WHERE id=1')
        row = c.fetchone()
        print(f"[DEBUG][set_global_time] just inserted row: {row}")
    except Exception as e:
        print(f"[DEBUG][set_global_time] error: {e}")
    finally:
        conn.close()

def get_global_time():
    """global_time 테이블에서 start, end를 반환. 없으면 (0.0, 0.0)"""
    ensure_global_time_table()
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute('SELECT start_time, end_time FROM global_time WHERE id=1')
        row = c.fetchone()
        print('[DEBUG][get_global_time] row:', row)
        if row:
            return row[0], row[1]
        else:
            return 0.0, 0.0
    finally:
        conn.close()

def ensure_time_segments_table():
    """Ensure the time_segments table exists in the database."""
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS time_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                start REAL NOT NULL,
                end REAL NOT NULL
            )
        ''')
        conn.commit()
    finally:
        conn.close()

def save_time_segment(name, start, end):
    """Save a time segment to the database."""
    ensure_time_segments_table()
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO time_segments (name, start, end)
            VALUES (?, ?, ?)
        ''', (name, start, end))
        conn.commit()
    finally:
        conn.close()

def get_time_segments():
    """Fetch all time segments from the database."""
    ensure_time_segments_table()
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute('SELECT id, name, start, end FROM time_segments ORDER BY id DESC')
        segments = c.fetchall()
        return [{'id': row[0], 'name': row[1], 'start': row[2], 'end': row[3]} for row in segments]
    finally:
        conn.close()

def delete_time_segment(segment_id):
    """Delete a time segment from the database by ID."""
    ensure_time_segments_table()
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute('DELETE FROM time_segments WHERE id = ?', (segment_id,))
        conn.commit()
        return c.rowcount > 0  # Return True if a row was deleted
    finally:
        conn.close()

def clear_time_segments():
    """
    Clear all time segments from the database
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Ensure time_segments table exists
        ensure_time_segments_table()
        
        # Clear all time segments
        c.execute('DELETE FROM time_segments')
        conn.commit()
        logger.info("All time segments cleared successfully")
        
    except Exception as e:
        logger.error(f"Error clearing time segments: {str(e)}")
        logger.error(traceback.format_exc())
        raise
    finally:
        if conn:
            conn.close()

def reset_database():
    """
    Completely reset the database - delete all data and reinitialize
    """
    global _db_initialized
    try:
        logger.info("Resetting database completely...")
        
        # Close any existing connections
        if os.path.exists(DB_PATH):
            try:
                os.chmod(DB_PATH, stat.S_IWRITE | stat.S_IREAD)
                os.remove(DB_PATH)
                logger.info("Existing database file removed for reset")
            except Exception as e:
                logger.error(f"Error removing existing database file: {str(e)}")
                logger.error(traceback.format_exc())
        
        # Reset initialization flag
        _db_initialized = False
        
        # Reinitialize database
        init_db()
        logger.info("Database reset completed successfully")
        
    except Exception as e:
        logger.error(f"Error resetting database: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def save_chart_layout(charts_info):
    """
    Save chart layout information to database
    charts_info: list of dictionaries containing chart information
    [
        {
            'chart_id': 'chart-123',
            'chart_order': 0,
            'parameters': ['param1', 'param2'],
            'scale_info': {
                'x': {'min': 0, 'max': 100},
                'y': {'min': -10, 'max': 10}
            }
        }
    ]
    """
    try:
        import json
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Ensure chart_layout table exists
        c.execute('''
            CREATE TABLE IF NOT EXISTS chart_layout (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chart_id TEXT NOT NULL,
                chart_order INTEGER NOT NULL,
                parameters TEXT,  -- JSON string of parameter names
                scale_info TEXT,  -- JSON string of scale information
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Clear existing chart layout data
        c.execute('DELETE FROM chart_layout')
        
        # Insert new chart layout data
        for chart_info in charts_info:
            parameters_json = json.dumps(chart_info.get('parameters', []))
            scale_info_json = json.dumps(chart_info.get('scale_info', {}))
            
            c.execute('''
                INSERT INTO chart_layout (chart_id, chart_order, parameters, scale_info)
                VALUES (?, ?, ?, ?)
            ''', (
                chart_info['chart_id'],
                chart_info['chart_order'],
                parameters_json,
                scale_info_json
            ))
        
        conn.commit()
        logger.info(f"Saved chart layout with {len(charts_info)} charts")
        
    except Exception as e:
        logger.error(f"Error saving chart layout: {str(e)}")
        logger.error(traceback.format_exc())
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

def get_chart_layout():
    """
    Retrieve chart layout information from database
    Returns: list of dictionaries containing chart information
    """
    try:
        import json
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Ensure chart_layout table exists
        c.execute('''
            CREATE TABLE IF NOT EXISTS chart_layout (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chart_id TEXT NOT NULL,
                chart_order INTEGER NOT NULL,
                parameters TEXT,  -- JSON string of parameter names
                scale_info TEXT,  -- JSON string of scale information
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Get chart layout data
        c.execute('''
            SELECT chart_id, chart_order, parameters, scale_info
            FROM chart_layout
            ORDER BY chart_order
        ''')
        
        rows = c.fetchall()
        charts_info = []
        
        for row in rows:
            chart_id, chart_order, parameters_json, scale_info_json = row
            
            try:
                parameters = json.loads(parameters_json) if parameters_json else []
                scale_info = json.loads(scale_info_json) if scale_info_json else {}
            except json.JSONDecodeError as e:
                logger.warning(f"Error parsing JSON for chart {chart_id}: {str(e)}")
                parameters = []
                scale_info = {}
            
            charts_info.append({
                'chart_id': chart_id,
                'chart_order': chart_order,
                'parameters': parameters,
                'scale_info': scale_info
            })
        
        logger.info(f"Retrieved chart layout with {len(charts_info)} charts")
        return charts_info
        
    except Exception as e:
        logger.error(f"Error getting chart layout: {str(e)}")
        logger.error(traceback.format_exc())
        return []
    finally:
        if conn:
            conn.close()

def clear_chart_layout():
    """
    Clear all chart layout information
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Ensure chart_layout table exists
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chart_layout (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chart_id TEXT NOT NULL,
                chart_order INTEGER NOT NULL,
                parameters TEXT,
                scale_info TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Clear all chart layout data
        cursor.execute('DELETE FROM chart_layout')
        conn.commit()
        logger.info("Chart layout cleared successfully")
        
    except Exception as e:
        logger.error(f"Error clearing chart layout: {str(e)}")
        logger.error(traceback.format_exc())
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

# Configuration 관련 함수들
def ensure_parameter_config_table():
    """
    Ensure that parameter_config table exists in the database
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 기존 테이블이 있는지 확인
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='parameter_config'")
        table_exists = cursor.fetchone()
        
        if table_exists:
            # 기존 테이블의 컬럼 구조 확인
            cursor.execute("PRAGMA table_info(parameter_config)")
            columns = [col[1] for col in cursor.fetchall()]
            
            # 새로운 컬럼들이 없는 경우 마이그레이션 수행
            if 'line1' not in columns:
                logger.info("Migrating parameter_config table to new schema...")
                
                # 임시 테이블 생성
                cursor.execute('''
                    CREATE TABLE parameter_config_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        parameter_name TEXT NOT NULL,
                        description TEXT,
                        type TEXT DEFAULT 'Raw',
                        formula TEXT,
                        custom_py TEXT,
                        lo REAL,
                        hi REAL,
                        line1 REAL,
                        line1_color TEXT DEFAULT '#FF0000',
                        line2 REAL,
                        line2_color TEXT DEFAULT '#00FF00',
                        line3 REAL,
                        line3_color TEXT DEFAULT '#0000FF',
                        line4 REAL,
                        line4_color TEXT DEFAULT '#FFFF00',
                        line5 REAL,
                        line5_color TEXT DEFAULT '#FF00FF',
                        line6 REAL,
                        line6_color TEXT DEFAULT '#00FFFF',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 기존 데이터를 새 테이블로 복사 (기존 limit_line_hi, limit_line_lo를 line1, line2로 매핑)
                cursor.execute('''
                    INSERT INTO parameter_config_new 
                    (parameter_name, description, type, formula, custom_py, lo, hi, line1, line1_color, line2, line2_color, line3, line3_color, line4, line4_color, line5, line5_color, line6, line6_color)
                    SELECT 
                        parameter_name, description, type, formula, custom_py, lo, hi,
                        limit_line_hi, '#FF0000', limit_line_lo, '#00FF00',
                        NULL, '#0000FF', NULL, '#FFFF00', NULL, '#FF00FF', NULL, '#00FFFF'
                    FROM parameter_config
                ''')
                
                # 기존 테이블 삭제
                cursor.execute('DROP TABLE parameter_config')
                
                # 새 테이블 이름 변경
                cursor.execute('ALTER TABLE parameter_config_new RENAME TO parameter_config')
                
                logger.info("Parameter config table migration completed")
        else:
            # 새 테이블 생성
            cursor.execute('''
                CREATE TABLE parameter_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parameter_name TEXT NOT NULL,
                    description TEXT,
                    type TEXT DEFAULT 'Raw',
                    formula TEXT,
                    custom_py TEXT,
                    lo REAL,
                    hi REAL,
                    line1 REAL,
                    line1_color TEXT DEFAULT '#FF0000',
                    line2 REAL,
                    line2_color TEXT DEFAULT '#00FF00',
                    line3 REAL,
                    line3_color TEXT DEFAULT '#0000FF',
                    line4 REAL,
                    line4_color TEXT DEFAULT '#FFFF00',
                    line5 REAL,
                    line5_color TEXT DEFAULT '#FF00FF',
                    line6 REAL,
                    line6_color TEXT DEFAULT '#00FFFF',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        
        conn.commit()
        logger.info("Parameter config table ensured")
        
    except Exception as e:
        logger.error(f"Error ensuring parameter config table: {str(e)}")
        logger.error(traceback.format_exc())
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

def save_parameter_config(config_data):
    """
    Save parameter configuration data
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Ensure table exists
        ensure_parameter_config_table()
        
        # Clear existing data
        cursor.execute('DELETE FROM parameter_config')
        
        # Insert new data
        for config in config_data:
            cursor.execute('''
                INSERT INTO parameter_config 
                (parameter_name, description, type, formula, custom_py, lo, hi, line1, line1_color, line2, line2_color, line3, line3_color, line4, line4_color, line5, line5_color, line6, line6_color)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                config.get('parameter_name', ''),
                config.get('description', ''),
                config.get('type', 'Raw'),
                config.get('formula', ''),
                config.get('custom_py', ''),
                config.get('lo', None),
                config.get('hi', None),
                config.get('line1', None),
                config.get('line1_color', '#FF0000'),
                config.get('line2', None),
                config.get('line2_color', '#00FF00'),
                config.get('line3', None),
                config.get('line3_color', '#0000FF'),
                config.get('line4', None),
                config.get('line4_color', '#FFFF00'),
                config.get('line5', None),
                config.get('line5_color', '#FF00FF'),
                config.get('line6', None),
                config.get('line6_color', '#00FFFF')
            ))
        
        conn.commit()
        logger.info(f"Saved {len(config_data)} parameter configurations")
        
    except Exception as e:
        logger.error(f"Error saving parameter config: {str(e)}")
        logger.error(traceback.format_exc())
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

def load_parameter_config():
    """
    Load parameter configuration data
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='parameter_config'")
        if not cursor.fetchone():
            return []
        
        # Load configuration data
        cursor.execute('''
            SELECT parameter_name, description, type, formula, custom_py, lo, hi, line1, line1_color, line2, line2_color, line3, line3_color, line4, line4_color, line5, line5_color, line6, line6_color
            FROM parameter_config
            ORDER BY parameter_name
        ''')
        
        rows = cursor.fetchall()
        config_data = []
        
        for row in rows:
            config_data.append({
                'parameter_name': row[0],
                'description': row[1] or '',
                'type': row[2] or 'Raw',
                'formula': row[3] or '',
                'custom_py': row[4] or '',
                'lo': row[5] if row[5] is not None else '',
                'hi': row[6] if row[6] is not None else '',
                'line1': row[7] if row[7] is not None and row[7] != 0 else '',
                'line1_color': row[8] if row[8] is not None else '#FF0000',
                'line2': row[9] if row[9] is not None and row[9] != 0 else '',
                'line2_color': row[10] if row[10] is not None else '#00FF00',
                'line3': row[11] if row[11] is not None and row[11] != 0 else '',
                'line3_color': row[12] if row[12] is not None else '#0000FF',
                'line4': row[13] if row[13] is not None and row[13] != 0 else '',
                'line4_color': row[14] if row[14] is not None else '#FFFF00',
                'line5': row[15] if row[15] is not None and row[15] != 0 else '',
                'line5_color': row[16] if row[16] is not None else '#FF00FF',
                'line6': row[17] if row[17] is not None and row[17] != 0 else '',
                'line6_color': row[18] if row[18] is not None else '#00FFFF'
            })
        
        logger.info(f"Loaded {len(config_data)} parameter configurations")
        return config_data
        
    except Exception as e:
        logger.error(f"Error loading parameter config: {str(e)}")
        logger.error(traceback.format_exc())
        return []
    finally:
        if conn:
            conn.close() 