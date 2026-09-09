from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import logging
import webbrowser
from threading import Timer
import sys
import sys
import shutil
import traceback
import stat
import time
from datetime import datetime
from backend.loader import process_file
from backend.db import (init_db, get_parameters, get_timeseries_data, 
                      debug_database, save_timeseries_data, cleanup_database,
                      get_global_start_time, get_global_end_time, get_global_time,
                      set_global_time, save_time_segment, get_time_segments,
                      delete_time_segment, clear_time_segments, reset_database,
                      save_chart_layout, get_chart_layout, clear_chart_layout,
                      save_parameter_config, load_parameter_config)
from backend.filters import apply_lowpass_filter, apply_bandpass_filter, apply_moving_average, get_filter_info
from backend.derived import execute_derived_parameter
from backend.bit_extractor import create_bit_extracted_parameter, get_bit_extractor_info
import struct
import sqlite3
import re
import json

# numpy와 scipy는 필요할 때만 import (지연 로딩)
_numpy_loaded = False
_scipy_loaded = False

def get_numpy():
    """numpy를 지연 로딩으로 가져오기"""
    global _numpy_loaded
    if not _numpy_loaded:
        logger.info("Loading numpy...")
        import numpy as np
        _numpy_loaded = True
        return np
    else:
        import numpy as np
        return np

def get_scipy():
    """scipy를 지연 로딩으로 가져오기"""
    global _scipy_loaded
    if not _scipy_loaded:
        logger.info("Loading scipy...")
        import scipy
        _scipy_loaded = True
        return scipy
    else:
        import scipy
        return scipy

# 실행 파일 기준 상대 경로로 설정
if getattr(sys, 'frozen', False):
    # PyInstaller로 패키징된 경우 (특히 단일파일 모드)
    # 임시 폴더를 사용 (templates, static 등이 포함된 곳)
    application_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    # 데이터 저장용 경로는 실행 파일 폴더 사용
    data_path = os.path.dirname(sys.executable)
else:
    # 일반 Python 실행의 경우
    application_path = os.path.dirname(os.path.abspath(__file__))
    data_path = application_path

# 로그 파일 경로 설정
log_file = os.path.join(data_path, 'wavelab.log')

# 프로그램 시작 시 기존 로그 파일 삭제
try:
    if os.path.exists(log_file):
        os.remove(log_file)
        print(f"기존 로그 파일 삭제됨: {log_file}")
except Exception as e:
    print(f"로그 파일 삭제 중 오류 발생: {str(e)}")

# 로거 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 기존 핸들러 제거 (중복 방지)
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# 파일 핸들러 설정
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# 콘솔 핸들러 설정
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# 핸들러 추가
logger.addHandler(file_handler)
logger.addHandler(console_handler)

logger.info("=== WaveLab V2.8 시작 ===")
logger.info(f"Application path set to: {application_path}")
logger.info(f"Log file path: {log_file}")

# Flask 앱 초기화 시 static_folder 경로 명시적 설정
if getattr(sys, 'frozen', False):
    # PyInstaller로 패키징된 경우
    static_folder = os.path.join(application_path, 'static')
    template_folder = os.path.join(application_path, 'templates')
else:
    # 일반 Python 실행의 경우
    static_folder = os.path.join(application_path, 'static')
    template_folder = os.path.join(application_path, 'templates')

app = Flask(__name__,
           static_folder=static_folder,
           template_folder=template_folder)
CORS(app)

# 지연 로딩을 위한 모듈 캐시
_module_cache = {}

def get_backend_module(module_name):
    """백엔드 모듈을 지연 로딩으로 가져오기"""
    if module_name not in _module_cache:
        logger.info(f"Loading backend module: {module_name}")
        if module_name == 'loader':
            from backend.loader import process_file
            _module_cache[module_name] = {'process_file': process_file}
        elif module_name == 'db':
            from backend.db import (init_db, get_parameters, get_timeseries_data, 
                                  debug_database, save_timeseries_data, cleanup_database,
                                  get_global_start_time, get_global_end_time, get_global_time,
                                  set_global_time, save_time_segment, get_time_segments,
                                  delete_time_segment, clear_time_segments, reset_database,
                                  save_chart_layout, get_chart_layout, clear_chart_layout,
                                  save_parameter_config, load_parameter_config)
            _module_cache[module_name] = {
                'init_db': init_db, 'get_parameters': get_parameters,
                'get_timeseries_data': get_timeseries_data, 'debug_database': debug_database,
                'save_timeseries_data': save_timeseries_data, 'cleanup_database': cleanup_database,
                'get_global_start_time': get_global_start_time, 'get_global_end_time': get_global_end_time,
                'get_global_time': get_global_time, 'set_global_time': set_global_time,
                'save_time_segment': save_time_segment, 'get_time_segments': get_time_segments,
                'delete_time_segment': delete_time_segment, 'clear_time_segments': clear_time_segments,
                'reset_database': reset_database, 'save_chart_layout': save_chart_layout,
                'get_chart_layout': get_chart_layout, 'clear_chart_layout': clear_chart_layout,
                'save_parameter_config': save_parameter_config, 'load_parameter_config': load_parameter_config
            }
        elif module_name == 'filters':
            from backend.filters import apply_lowpass_filter, apply_bandpass_filter, apply_moving_average, get_filter_info, apply_rms
            _module_cache[module_name] = {
                'apply_lowpass_filter': apply_lowpass_filter,
                'apply_bandpass_filter': apply_bandpass_filter,
                'apply_moving_average': apply_moving_average,
                'get_filter_info': get_filter_info,
                'apply_rms': apply_rms
            }
        elif module_name == 'derived':
            from backend.derived import execute_derived_parameter
            _module_cache[module_name] = {'execute_derived_parameter': execute_derived_parameter}
        elif module_name == 'bit_extractor':
            from backend.bit_extractor import create_bit_extracted_parameter, get_bit_extractor_info
            _module_cache[module_name] = {
                'create_bit_extracted_parameter': create_bit_extracted_parameter,
                'get_bit_extractor_info': get_bit_extractor_info
            }
    return _module_cache[module_name]

# 오류 핸들러 추가
@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal Server Error: {str(error)}")
    logger.error(traceback.format_exc())
    return jsonify({'error': 'Internal Server Error', 'details': str(error)}), 500

@app.errorhandler(404)
def not_found_error(error):
    logger.error(f"Not Found Error: {str(error)}")
    return jsonify({'error': 'Not Found', 'details': str(error)}), 404

# 모든 요청 전에 실행되는 미들웨어
@app.before_request
def before_request():
    logger.info(f"Request: {request.method} {request.path}")
    logger.info(f"Request Headers: {dict(request.headers)}")
    if request.is_json:
        logger.info(f"Request JSON: {request.get_json()}")

# 모든 응답 후에 실행되는 미들웨어
@app.after_request
def after_request(response):
    logger.info(f"Response: {response.status}")
    return response

def ensure_directory_with_permissions(directory_path):
    """디렉토리가 존재하는지 확인하고, 없다면 생성하며 쓰기 권한 확인"""
    try:
        if not os.path.exists(directory_path):
            os.makedirs(directory_path)
            logger.info(f"Created directory: {directory_path}")
        
        # 쓰기 권한 확인
        if not os.access(directory_path, os.W_OK):
            # 쓰기 권한 추가
            os.chmod(directory_path, stat.S_IWRITE | stat.S_IEXEC | stat.S_IREAD)
            logger.info(f"Added write permissions to directory: {directory_path}")
        
        # 테스트 파일 생성 시도
        test_file = os.path.join(directory_path, '.test_write')
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            logger.info(f"Write permission test successful for: {directory_path}")
        except Exception as e:
            logger.error(f"Write permission test failed for {directory_path}: {str(e)}")
            raise Exception(f"No write permission for directory: {directory_path}")
            
        return True
    except Exception as e:
        logger.error(f"Error ensuring directory permissions: {str(e)}")
        logger.error(traceback.format_exc())
        return False

# Ensure required directories exist with proper permissions
UPLOAD_FOLDER = os.path.join(data_path, 'uploads')
DATA_FOLDER = os.path.join(data_path, 'data')

try:
    if not ensure_directory_with_permissions(UPLOAD_FOLDER):
        raise Exception(f"Failed to create or set permissions for upload directory: {UPLOAD_FOLDER}")
    if not ensure_directory_with_permissions(DATA_FOLDER):
        raise Exception(f"Failed to create or set permissions for data directory: {DATA_FOLDER}")
except Exception as e:
    logger.error(f"Directory setup failed: {str(e)}")
    logger.error(traceback.format_exc())
    raise

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024  # 10GB max file size

def cleanup_upload_folder():
    """업로드 폴더의 모든 파일 삭제"""
    try:
        if not os.path.exists(UPLOAD_FOLDER):
            logger.warning(f"Upload folder does not exist: {UPLOAD_FOLDER}")
            return
            
        for filename in os.listdir(UPLOAD_FOLDER):
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            try:
                if os.path.isfile(file_path):
                    os.chmod(file_path, stat.S_IWRITE)  # 파일에 쓰기 권한 추가
                    os.remove(file_path)
            except Exception as e:
                logger.error(f"Error removing file {file_path}: {str(e)}")
                logger.error(traceback.format_exc())
                
        logger.info("Upload folder cleaned successfully")
    except Exception as e:
        logger.error(f"Error cleaning upload folder: {str(e)}")
        logger.error(traceback.format_exc())

# Initialize database (지연 로딩 적용)
def initialize_database():
    """데이터베이스 초기화를 지연 로딩으로 수행"""
    try:
        logger.info("Initializing database...")
        db_module = get_backend_module('db')
        db_module['init_db']()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        logger.error(traceback.format_exc())
        raise

# Heartbeat 관련 변수
last_heartbeat_time = time.time()
heartbeat_timeout = 10800  # 3시간 동안 heartbeat가 없으면 종료
heartbeat_check_interval = 300  # 5분마다 heartbeat 체크

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    if getattr(sys, 'frozen', False):
        # PyInstaller로 패키징된 경우
        static_path = os.path.join(application_path, 'static')
    else:
        # 일반 Python 실행의 경우
        static_path = os.path.join(app.root_path, 'static')
    
    return send_from_directory(static_path,
                             'WaveLab_V3.0.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        logger.error("No file part in request")
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if not file.filename:
        logger.error("No selected file")
        return jsonify({'error': 'No selected file'}), 400
    
    # Ensure filename is string
    filename_str = file.filename
    
    # Get file type (regular or fixed-wing)
    file_type = request.form.get('file_type', 'regular')
    logger.info(f"Uploading file with type: {file_type}")
    
    # Check file extension
    file_ext = os.path.splitext(filename_str)[1].lower()
    if file_ext not in ['.mat', '.matlab', '.csv', '.db']:
        logger.error(f"Invalid file type: {filename_str}")
        return jsonify({'error': 'Invalid file type. Supported formats: .mat, .matlab, .csv, .db'}), 400
    
    db_module = None
    
    try:
        # 업로드 폴더 정리
        cleanup_upload_folder()
        
        filename = os.path.join(app.config['UPLOAD_FOLDER'], filename_str)
        logger.info(f"Saving file to: {filename}")
        
        # 파일 저장 시도
        try:
            file.save(filename)
            # 파일에 쓰기 권한 추가
            os.chmod(filename, stat.S_IWRITE | stat.S_IREAD)
        except Exception as e:
            logger.error(f"Error saving file: {str(e)}")
            logger.error(traceback.format_exc())
            return jsonify({'error': f'Failed to save file: {str(e)}'}), 500
        
        # .db 파일인 경우 데이터베이스 교체
        if file_ext == '.db':
            try:
                # 새 데이터베이스로 교체
                current_db = os.path.join(data_path, 'data', 'timeseries.db')
                shutil.copy2(filename, current_db)
                logger.info(f"Replaced database with: {filename}")
                
                # .db 파일은 저장된 데이터베이스이므로 time segment를 초기화하지 않음
                # (저장된 데이터베이스에는 time segment 정보가 포함되어 있음)
                logger.info("Database replaced - time segments preserved from saved database")
                
                # 파라미터 목록 확인
                try:
                    db_module = get_backend_module('db')
                    parameters = db_module['get_parameters']()
                    if not parameters:
                        logger.warning("No parameters found in uploaded database")
                        return jsonify({'error': 'No parameters found in uploaded database'}), 500
                    
                    # 차트 레이아웃 정보 가져오기
                    chart_layout = db_module['get_chart_layout']()
                    logger.info(f"Retrieved chart layout with {len(chart_layout)} charts")
                        
                    logger.info(f"Successfully loaded database with parameters: {parameters}")
                    return jsonify({
                        'message': 'Database uploaded and loaded successfully', 
                        'parameters': parameters,
                        'chart_layout': chart_layout
                    })
                except Exception as e:
                    logger.error(f"Error getting parameters from uploaded database: {str(e)}")
                    logger.error(traceback.format_exc())
                    return jsonify({'error': f'Error loading database: {str(e)}'}), 500
                    
            except Exception as e:
                logger.error(f"Error replacing database: {str(e)}")
                logger.error(traceback.format_exc())
                return jsonify({'error': f'Error replacing database: {str(e)}'}), 500
        else:
            # 새로운 파일 업로드 시 기존 데이터베이스 초기화
            try:
                logger.info("Resetting database for new file upload...")
                db_module = get_backend_module('db')
                db_module['reset_database']()
                logger.info("Database reset successfully for new file")
            except Exception as e:
                logger.error(f"Error resetting database for new file: {str(e)}")
                logger.error(traceback.format_exc())
                return jsonify({'error': f'Error resetting database: {str(e)}'}), 500
            
            # Process the file (기존 .mat, .csv 처리)
            try:
                loader_module = get_backend_module('loader')
                loader_module['process_file'](filename, file_type=file_type)
            except Exception as e:
                logger.error(f"Error processing file: {str(e)}")
                logger.error(traceback.format_exc())
                return jsonify({'error': f'Error processing file: {str(e)}'}), 500
            
            # Time segments 초기화
            try:
                db_module['clear_time_segments']()
                logger.info("Cleared time segments after file processing")
            except Exception as e:
                logger.error(f"Error clearing time segments: {str(e)}")
                logger.error(traceback.format_exc())
            
            # 차트 레이아웃 초기화 (새 파일이므로)
            try:
                db_module['clear_chart_layout']()
                logger.info("Cleared chart layout after file processing")
            except Exception as e:
                logger.error(f"Error clearing chart layout: {str(e)}")
                logger.error(traceback.format_exc())
            
            # 디버그 정보 출력
            try:
                db_module['debug_database']()
            except Exception as e:
                logger.error(f"Error debugging database: {str(e)}")
                logger.error(traceback.format_exc())
            
            # 파라미터 목록 확인
            try:
                parameters = db_module['get_parameters']()
                if not parameters:
                    logger.warning("No parameters found after processing file")
                    return jsonify({'error': 'No parameters found in processed file'}), 500
                    
                logger.info(f"Successfully processed file with parameters: {parameters}")
                return jsonify({'message': 'File uploaded and processed successfully', 'parameters': parameters})
            except Exception as e:
                logger.error(f"Error getting parameters: {str(e)}")
                logger.error(traceback.format_exc())
                return jsonify({'error': f'Error getting parameters: {str(e)}'}), 500
        
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/parameters')
def get_parameters_list():
    try:
        logger.info("Fetching parameters list")
        # 디버그 정보 출력
        try:
            db_module = get_backend_module('db')
            db_module['debug_database']()
        except Exception as e:
            logger.error(f"Error debugging database: {str(e)}")
            logger.error(traceback.format_exc())
            
        parameters = db_module['get_parameters']()
        if not parameters:
            logger.warning("No parameters found in database")
            return jsonify([])
        logger.info(f"Found parameters: {parameters}")
        return jsonify(parameters)
    except Exception as e:
        logger.error(f"Error fetching parameters: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/data')
def get_data():
    parameter = request.args.get('parameter')
    start = float(request.args.get('start', -float('inf')))
    end = float(request.args.get('end', float('inf')))
    resolution = request.args.get('resolution', type=int, default=None)
    
    try:
        logger.info(f"Fetching data for parameter: {parameter}, start: {start}, end: {end}, resolution: {resolution}")
        db_module = get_backend_module('db')
        data = db_module['get_timeseries_data'](parameter, start, end, resolution=resolution)
        logger.info(f"Retrieved data points: {len(data['time'])}")
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error fetching data: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/filter', methods=['POST'])
def apply_filter():
    try:
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({'error': 'Invalid JSON data'}), 400
            
        parameter = data.get('parameter')
        filter_type = data.get('filter_type')
        params = data.get('params', {})
        
        if not parameter or not filter_type:
            return jsonify({'error': 'Missing required parameters'}), 400
            
        # Get numpy first
        np = get_numpy()
            
        # Get original data (always use level 0 for filtering)
        # file_type='raw'로 호출하여 변환 전 time을 받음
        db_module = get_backend_module('db')
        data_ts = db_module['get_timeseries_data'](parameter, -np.inf, np.inf, file_type='raw')
        if not data_ts or not data_ts['time'] or not data_ts['value']:
            return jsonify({'error': 'No data available for filtering'}), 400
            
        # Convert data to numpy arrays (copy to avoid modifying original)
        time_array = np.array(data_ts['time'], dtype=np.float64).copy()
        value_array = np.array(data_ts['value'], dtype=np.float64).copy()
        
        # Calculate sampling frequency
        time_diff = np.diff(time_array)
        logger.info(f"Time array stats: min={np.min(time_array)}, max={np.max(time_array)}, len={len(time_array)}")
        logger.info(f"Time differences: min={np.min(time_diff)}, max={np.max(time_diff)}, mean={np.mean(time_diff)}, std={np.std(time_diff)}")
        
        # Calculate sampling frequency from median time difference
        sampling_freq = 1.0 / np.median(time_diff)
        logger.info(f"Calculated sampling frequency: {sampling_freq:.2f} Hz")
        
        filtered_data = None
        filtered_parameter = None

        # Apply filter based on type
        if filter_type == 'lpf':
            cutoff_freq = params['cutoff_freq']
            order = params['order']
            
            # Normalize cutoff frequency
            Wn = cutoff_freq / (sampling_freq / 2)
            logger.info(f"cutoff_freq(Hz): {cutoff_freq}, Wn: {Wn}, order: {order}")
            logger.info(f"Before filtering: min={np.min(value_array)}, max={np.max(value_array)}, mean={np.mean(value_array)}, std={np.std(value_array)}")
            filtered_data = get_backend_module('filters')['apply_lowpass_filter'](
                value_array,
                cutoff_freq,  # Hz 단위로 전달
                order,
                sampling_freq  # 샘플링 주파수 추가
            )
            logger.info(f"After filtering: min={np.min(filtered_data)}, max={np.max(filtered_data)}, mean={np.mean(filtered_data)}, std={np.std(filtered_data)}")
            if np.sum(np.isfinite(filtered_data)) > 0:
                valid_idx = np.where(np.isfinite(filtered_data))[0]
                filtered_data = filtered_data[valid_idx]
                time_array = time_array[valid_idx]
            
            filtered_parameter = f"{parameter}_LPF_{cutoff_freq}Hz_{order}order"
            
        elif filter_type == 'bpf':
            low_freq = params['low_freq']
            high_freq = params['high_freq']
            order = params['order']
            
            # Normalize cutoff frequencies
            Wn = [low_freq / (sampling_freq / 2), high_freq / (sampling_freq / 2)]
            logger.info(f"low_freq(Hz): {low_freq}, high_freq(Hz): {high_freq}, Wn: {Wn}")
            filtered_data = get_backend_module('filters')['apply_bandpass_filter'](
                value_array,
                low_freq,  # Hz 단위로 전달
                high_freq,  # Hz 단위로 전달
                order,
                sampling_freq  # 샘플링 주파수 추가
            )
            
            filtered_parameter = f"{parameter}_BPF_{low_freq}_{high_freq}Hz_{order}order"
            
        elif filter_type == 'ma':
            window_size = params['window_size']
            if window_size <= 0:
                return jsonify({'error': 'Invalid window size'}), 400
                
            filtered_data = get_backend_module('filters')['apply_moving_average'](
                value_array,
                window_size,
                sampling_freq  # 샘플링 주파수 추가
            )
            
            filtered_parameter = f"{parameter}_MA_{params['window_size']}window"

        elif filter_type == 'rms':
            window_size = params['window_size']
            if window_size <= 0:
                return jsonify({'error': 'Invalid window size'}), 400
                
            filtered_data = get_backend_module('filters')['apply_rms'](
                value_array,
                window_size,
                sampling_freq
            )
            
            filtered_parameter = f"{parameter}_RMS_{params['window_size']}window"
        else:
             return jsonify({'error': f'Unknown filter type: {filter_type}'}), 400

        if filtered_data is None:
             return jsonify({'error': 'Filtering failed'}), 500
            
        filtered_data = np.array(filtered_data, dtype=np.float64)
        filtered_data[~np.isfinite(filtered_data)] = 0
        
        # Save filtered data with a new parameter name
        db_module = get_backend_module('db')
        db_module['save_timeseries_data'](filtered_parameter, time_array, filtered_data, 0)
        
        # Get filter information
        filter_info = get_backend_module('filters')['get_filter_info'](filter_type, {
            **params,
            'time_data': time_array.tolist()  # 시간 데이터 추가
        })
        
        return jsonify({
            'parameter': filtered_parameter,
            'filter_info': {
                'type': filter_type,
                'parameters': params,
                'formula': filter_info['formula'],
                'description': filter_info['description'],
                'frequency_response': filter_info['frequency_response']
            },
            'refresh_parameters': True  # 파라미터 리스트 갱신을 위한 플래그 추가
        })
        
    except Exception as e:
        logger.error(f"Error applying filter: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/data_count')
def get_data_count():
    parameter = request.args.get('parameter')
    start = float(request.args.get('start', 0))
    end = float(request.args.get('end', 0))
    try:
        db_module = get_backend_module('db')
        data = db_module['get_timeseries_data'](parameter, start, end)
        return jsonify({'count': len(data['time'])})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/derived', methods=['POST'])
def create_derived_parameter():
    try:
        data = request.get_json(silent=True) or {}
        parameter_name = data.get('name')
        code = data.get('code')
        parameters = data.get('parameters', [])
        
        if not parameter_name or not code:
            return jsonify({'error': 'Missing required parameters'}), 400
            
        # Get data for all parameters
        parameter_data = {}
        np = get_numpy()
        db_module = get_backend_module('db')
        
        for param_name in parameters:
            param_data = db_module['get_timeseries_data'](param_name, -np.inf, np.inf)
            if not param_data or not param_data['value']:
                return jsonify({'error': f'No data available for parameter: {param_name}'}), 400
            parameter_data[param_name] = param_data['value']
        
        # Execute the code to generate the derived parameter
        try:
            result = get_backend_module('derived')['execute_derived_parameter'](code, parameter_data)
            
            # Save the derived parameter
            db_module = get_backend_module('db')
            time_data = db_module['get_timeseries_data'](parameters[0], -np.inf, np.inf)['time']
            db_module['save_timeseries_data'](parameter_name, time_data, result, 0)
            
            return jsonify({
                'message': 'Derived parameter created successfully',
                'parameter': parameter_name
            })
            
        except Exception as e:
            logger.error(f"Error executing derived parameter code: {str(e)}")
            logger.error(traceback.format_exc())
            return jsonify({'error': str(e)}), 500
            
    except Exception as e:
        logger.error(f"Error creating derived parameter: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/save_database', methods=['POST'])
def save_database():
    try:
        data = request.get_json(silent=True) or {}
        file_name = data.get('file_name')
        charts_info = data.get('charts_info', [])  # 차트 정보 추가
        
        if not file_name or not file_name.endswith('.db'):
            return jsonify({'error': '파일명을 입력하세요(.db 확장자 포함)'}), 400
        
        save_path = os.path.join(data_path, 'data', file_name)
        current_db = os.path.join(data_path, 'data', 'timeseries.db')
        
        # 현재 데이터베이스를 임시로 복사
        temp_db = os.path.join(data_path, 'data', 'temp_timeseries.db')
        shutil.copy2(current_db, temp_db)
        
        try:
            # 차트 레이아웃 정보 저장
            if charts_info:
                db_module = get_backend_module('db')
                db_module['save_chart_layout'](charts_info)
                logger.info(f"Saved chart layout with {len(charts_info)} charts")
            
            # 최종 데이터베이스 파일로 복사
            shutil.copy2(current_db, save_path)
            
            return jsonify({
                'success': True,
                'message': 'DB가 성공적으로 저장되었습니다.',
                'path': f'data/{file_name}'
            })
        finally:
            # 임시 파일 정리
            if os.path.exists(temp_db):
                try:
                    os.remove(temp_db)
                except Exception as e:
                    logger.warning(f"Failed to remove temp database: {str(e)}")
                    
    except Exception as e:
        logger.error(f"Error saving database: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/download_database')
def download_database():
    db_path = os.path.join(data_path, 'data', 'timeseries.db')
    return send_from_directory(os.path.dirname(db_path), os.path.basename(db_path), as_attachment=True)

@app.route('/api/global_time')
def get_global_time_api():
    try:
        db_module = get_backend_module('db')
        start, end = db_module['get_global_time']()
        return jsonify({'start': start, 'end': end})
    except Exception as e:
        logger.error(f"Error fetching global time: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/time_segment', methods=['POST'])
def api_save_time_segment():
    try:
        data = request.get_json(silent=True) or {}
        name = data.get('name')
        start = data.get('start')
        end = data.get('end')
        if not name or start is None or end is None:
            return jsonify({'error': 'Missing required fields'}), 400
        db_module = get_backend_module('db')
        db_module['save_time_segment'](name, float(start), float(end))
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error saving time segment: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/time_segment', methods=['GET'])
def api_get_time_segments():
    try:
        db_module = get_backend_module('db')
        segments = db_module['get_time_segments']()
        return jsonify(segments)
    except Exception as e:
        logger.error(f"Error fetching time segments: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/time_segment/<int:segment_id>', methods=['DELETE'])
def api_delete_time_segment(segment_id):
    try:
        db_module = get_backend_module('db')
        success = db_module['delete_time_segment'](segment_id)
        if success:
            return jsonify({'success': True, 'message': 'Time segment deleted successfully'})
        else:
            return jsonify({'error': 'Time segment not found'}), 404
    except Exception as e:
        logger.error(f"Error deleting time segment: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/export_pcap', methods=['POST'])
def export_pcap():
    try:
        data = request.get_json(silent=True) or {}
        parameters = data.get('parameters', [])
        format_type = data.get('format', '32bit')
        filename = data.get('filename', 'exported_data')
        
        if not parameters:
            return jsonify({'error': 'No parameters selected'}), 400
        
        # 모든 파라미터의 데이터와 시간 가져오기
        all_data = {}
        all_time = {}
        global_time_data = None
        
        for param in parameters:
            try:
                np = get_numpy()
                db_module = get_backend_module('db')
                tsdata = db_module['get_timeseries_data'](param, -np.inf, np.inf)
                if tsdata and tsdata['time'] and tsdata['value']:
                    all_data[param] = tsdata['value']
                    all_time[param] = tsdata['time']
                    if global_time_data is None:
                        global_time_data = tsdata['time']
                else:
                    logger.warning(f"No data available for parameter: {param}")
            except Exception as e:
                logger.error(f"Error getting data for parameter {param}: {str(e)}")
                return jsonify({'error': f'Error getting data for parameter {param}'}), 500
        
        if not all_data:
            return jsonify({'error': 'No valid data found for selected parameters'}), 400
        
        # PCAP 파일 생성
        pcap_data = create_pcap_file_with_param_time(all_data, all_time, format_type)
        
        # 파일로 저장
        pcap_filename = f"{filename}.pcap"
        pcap_path = os.path.join(app.config['UPLOAD_FOLDER'], pcap_filename)
        
        with open(pcap_path, 'wb') as f:
            f.write(pcap_data)
        
        logger.info(f"PCAP file created: {pcap_path}")
        
        return send_from_directory(
            app.config['UPLOAD_FOLDER'], 
            pcap_filename, 
            as_attachment=True,
            download_name=pcap_filename
        )
        
    except Exception as e:
        logger.error(f"Error exporting PCAP: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/bit_extractor', methods=['POST'])
def create_bit_extracted_parameter_api():
    """
    BIT Extractor를 사용하여 새로운 파라미터를 생성합니다.
    """
    try:
        data = request.get_json(silent=True) or {}
        source_parameter = data.get('source_parameter')
        lsb = data.get('lsb')
        msb = data.get('msb')
        data_format = data.get('data_format', '32bit')
        sign_bit_index = data.get('sign_bit_index')
        lsb_scale = data.get('lsb_scale', 1.0)
        parameter_name = data.get('parameter_name')
        
        # 필수 파라미터 검증
        if not source_parameter or lsb is None or msb is None:
            return jsonify({'error': 'Missing required parameters: source_parameter, lsb, msb'}), 400
        if not parameter_name:
            return jsonify({'error': 'Missing parameter_name'}), 400
        
        # 데이터 포맷 검증
        if data_format not in ['32bit', '16bit']:
            return jsonify({'error': 'Invalid data format. Must be 32bit or 16bit'}), 400
        
        # 비트 인덱스 검증
        max_bits = 32 if data_format == '32bit' else 16
        if lsb < 0 or msb < 0 or lsb >= max_bits or msb >= max_bits:
            return jsonify({'error': f'Bit indices must be between 0 and {max_bits-1}'}), 400
        
        # 부호 비트 인덱스 검증
        if sign_bit_index is not None:
            if sign_bit_index < 0 or sign_bit_index >= max_bits:
                return jsonify({'error': f'Sign bit index must be between 0 and {max_bits-1}'}), 400
        
        # LSB와 MSB의 순서는 자유롭게 허용 (역순 추출 지원)
        
        logger.info(f"Creating bit extracted parameter:")
        logger.info(f"  Source parameter: {source_parameter}")
        logger.info(f"  LSB: {lsb}, MSB: {msb}")
        logger.info(f"  Data format: {data_format}")
        logger.info(f"  Sign bit index: {sign_bit_index}")
        logger.info(f"  LSB scale: {lsb_scale}")
        logger.info(f"  Parameter name: {parameter_name}")
        
        # BIT Extractor 실행
        new_parameter_name, progress_info = get_backend_module('bit_extractor')['create_bit_extracted_parameter'](
            source_parameter=source_parameter,
            lsb=lsb,
            msb=msb,
            data_format=data_format,
            sign_bit_index=sign_bit_index,
            lsb_scale=lsb_scale,
            parameter_name=parameter_name
        )
        
        # BIT Extractor 정보 가져오기
        bit_info = get_backend_module('bit_extractor')['get_bit_extractor_info'](
            source_parameter=source_parameter,
            lsb=lsb,
            msb=msb,
            data_format=data_format,
            sign_bit_index=sign_bit_index,
            lsb_scale=lsb_scale
        )
        
        return jsonify({
            'success': True,
            'parameter_name': new_parameter_name,
            'bit_info': {
                'formula': bit_info['formula'],
                'description': bit_info['description'],
                'parameters': bit_info['parameters']
            },
            'progress': progress_info['progress_percentage'],
            'progress_info': progress_info,
            'data_info': {
                'total_points': progress_info['total_points'],
                'estimated_time_ms': progress_info['total_points'] * 0.1  # 데이터 포인트당 0.1ms 예상
            },
            'refresh_parameters': True  # 파라미터 리스트 갱신을 위한 플래그
        })
        
    except Exception as e:
        logger.error(f"Error creating bit extracted parameter: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/session_notes', methods=['GET'])
def get_session_notes():
    """Session Notes를 데이터베이스에서 가져옵니다."""
    try:
        import sqlite3
        db_path = os.path.join(data_path, 'data', 'timeseries.db')
        
        if not os.path.exists(db_path):
            return jsonify({'success': True, 'notes': ''})
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # session_notes 테이블이 없으면 생성
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS session_notes (
                id INTEGER PRIMARY KEY,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 최신 Session Notes 가져오기
        cursor.execute('SELECT notes FROM session_notes ORDER BY updated_at DESC LIMIT 1')
        result = cursor.fetchone()
        
        conn.close()
        
        notes = result[0] if result else ''
        return jsonify({'success': True, 'notes': notes})
        
    except Exception as e:
        logger.error(f"Error getting session notes: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/session_notes', methods=['POST'])
def save_session_notes():
    """Session Notes를 데이터베이스에 저장합니다."""
    try:
        data = request.get_json(silent=True) or {}
        notes = data.get('notes', '')
        
        import sqlite3
        db_path = os.path.join(data_path, 'data', 'timeseries.db')
        
        if not os.path.exists(db_path):
            return jsonify({'error': 'Database not found'}), 404
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # session_notes 테이블이 없으면 생성
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS session_notes (
                id INTEGER PRIMARY KEY,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 기존 Session Notes가 있으면 업데이트, 없으면 새로 생성
        cursor.execute('SELECT id FROM session_notes ORDER BY updated_at DESC LIMIT 1')
        result = cursor.fetchone()
        
        if result:
            # 기존 노트 업데이트
            cursor.execute('''
                UPDATE session_notes 
                SET notes = ?, updated_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (notes, result[0]))
        else:
            # 새 노트 생성
            cursor.execute('''
                INSERT INTO session_notes (notes) VALUES (?)
            ''', (notes,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error saving session notes: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/shutdown', methods=['POST'])
def shutdown_server():
    """서버를 종료합니다."""
    try:
        logger.info("Received shutdown request from client")
        
        # 새로운 스레드에서 종료를 처리하여 응답을 먼저 보낼 수 있도록 함
        def shutdown():
            time.sleep(0.5)  # 응답이 전송될 시간을 줌
            logger.info("Shutting down server...")
            
            # 정리 작업 수행
            try:
                cleanup_database()
                cleanup_upload_folder()
                logger.info("Cleanup completed")
            except Exception as e:
                logger.error(f"Error during cleanup: {str(e)}")
            
            # 강제 종료
            os._exit(0)
        
        import threading
        shutdown_thread = threading.Thread(target=shutdown)
        shutdown_thread.daemon = True
        shutdown_thread.start()
        
        return jsonify({'success': True, 'message': 'Server shutting down...'})
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    """클라이언트 연결 상태를 확인하는 heartbeat 엔드포인트"""
    global last_heartbeat_time
    try:
        data = request.json or {}
        client_id = data.get('client_id', 'unknown')
        last_heartbeat_time = time.time()
        logger.info(f"Heartbeat received from client: {client_id}")
        return jsonify({'success': True, 'timestamp': time.time()})
    except Exception as e:
        logger.error(f"Error in heartbeat: {str(e)}")
        return jsonify({'error': str(e)}), 500

def check_heartbeat():
    """Heartbeat 체크 함수 - 클라이언트 연결이 끊어졌는지 확인"""
    global last_heartbeat_time
    while True:
        try:
            current_time = time.time()
            if current_time - last_heartbeat_time > heartbeat_timeout:
                logger.warning(f"No heartbeat received for {heartbeat_timeout} seconds, shutting down server...")
                
                # 정리 작업 수행
                try:
                    cleanup_database()
                    cleanup_upload_folder()
                    logger.info("Cleanup completed before shutdown")
                except Exception as e:
                    logger.error(f"Error during cleanup: {str(e)}")
                
                # 강제 종료
                os._exit(0)
            
            time.sleep(heartbeat_check_interval)
        except Exception as e:
            logger.error(f"Error in heartbeat check: {str(e)}")
            time.sleep(heartbeat_check_interval)

# Heartbeat 체크 스레드 시작
import threading
heartbeat_thread = threading.Thread(target=check_heartbeat, daemon=True)
heartbeat_thread.start()

def create_pcap_file_with_param_time(data_dict, time_dict, format_type):
    """
    각 파라미터별로 그룹 시작 시간(해당 파라미터의 time 배열에서)을 헤더에 포함하여 PCAP 파일 생성
    """
    # PCAP 파일 헤더 (24 bytes)
    pcap_header = struct.pack('<IHHiIII',
        0xa1b2c3d4, 2, 1, 0, 0, 65535, 1
    )
    # 이더넷/IP/UDP 헤더
    ethernet_header = struct.pack('!6s6sH', b'\x00\x0c\x29\x12\x34\x56', b'\x00\x0c\x29\xab\xcd\xef', 0x0800)
    ip_header = struct.pack('!BBHHHBBH4s4s', 69, 0, 0, 12345, 0, 64, 17, 0, b'\xc0\xa8\x01\x01', b'\xc0\xa8\x01\x02')
    udp_header = struct.pack('!HHHH', 12345, 54321, 0, 0)
    pcap_data = bytearray(pcap_header)
    # 10분 단위 그룹화
    # 기준 시간은 모든 파라미터 중 가장 긴 time 배열 사용
    ref_time = None
    for t in time_dict.values():
        if ref_time is None or len(t) > len(ref_time):
            ref_time = t
    if not ref_time:
        return bytes(pcap_data)
    time_window = 600
    current_time = ref_time[0]
    time_groups = []
    current_group = []
    for i, timestamp in enumerate(ref_time):
        if timestamp - current_time >= time_window:
            if current_group:
                time_groups.append(current_group)
            current_group = [i]
            current_time = timestamp
        else:
            current_group.append(i)
    if current_group:
        time_groups.append(current_group)
    for group_idx, time_indices in enumerate(time_groups):
        payload = bytearray()
        # 16bit/32bit 헤더 추가
        if format_type == '16bit':
            payload.extend(struct.pack('BBBB', 0x21, 0x10, 0x08, 0x00))  # 1553
        else:
            payload.extend(struct.pack('BBBB', 0xA1, 0x00, 0x00, 0x00))  # Arinc-429
        # 각 파라미터별 그룹 시작 시간(해당 파라미터의 time 배열에서)
        for param_name, param_data in data_dict.items():
            param_name_bytes = param_name.encode('utf-8')
            payload.extend(struct.pack('<H', len(param_name_bytes)))
            payload.extend(param_name_bytes)
            # 파라미터별 그룹 시작 시간
            param_time_data = time_dict[param_name]
            param_group_start_time = param_time_data[time_indices[0]] if time_indices else 0
            payload.extend(struct.pack('<f', param_group_start_time))
            payload.extend(struct.pack('<I', len(time_indices)))
            for idx in time_indices:
                if idx < len(param_data):
                    value = param_data[idx]
                    if format_type == '32bit':
                        payload.extend(struct.pack('<f', float(value)))
                    else:
                        scaled_value = int(value * 1000)
                        payload.extend(struct.pack('<h', scaled_value))
        packet_ethernet = bytearray(ethernet_header)
        packet_ip = bytearray(ip_header)
        packet_udp = bytearray(udp_header)
        total_length = 20 + 8 + len(payload)
        packet_ip[2:4] = struct.pack('!H', total_length)
        udp_length = 8 + len(payload)
        packet_udp[4:6] = struct.pack('!H', udp_length)
        ip_checksum = calculate_checksum(packet_ip)
        packet_ip[10:12] = struct.pack('!H', ip_checksum)
        packet_data = packet_ethernet + packet_ip + packet_udp + payload
        # 그룹의 기준 파라미터(ref_time)의 시작 시간으로 타임스탬프
        group_start_time = ref_time[time_indices[0]] if time_indices else 0
        packet_timestamp = int(group_start_time * 1000000)
        packet_header = struct.pack('<IIII',
            packet_timestamp & 0xFFFFFFFF,
            (packet_timestamp >> 32) & 0xFFFFFFFF,
            len(packet_data),
            len(packet_data)
        )
        pcap_data.extend(packet_header)
        pcap_data.extend(packet_data)
    return bytes(pcap_data)

def calculate_checksum(data):
    """IP 체크섬을 계산합니다."""
    if len(data) % 2 == 1:
        data += b'\x00'
    
    checksum = 0
    for i in range(0, len(data), 2):
        checksum += (data[i] << 8) + data[i + 1]
    
    while checksum >> 16:
        checksum = (checksum & 0xFFFF) + (checksum >> 16)
    
    return ~checksum & 0xFFFF

# Configuration 관련 API 엔드포인트들
@app.route('/api/config/upload', methods=['POST'])
def upload_config_file():
    """Configuration 파일을 업로드하고 파싱합니다."""
    db_module = None # Initialize to avoid unbound variable warning
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'No selected file'}), 400
        
        # 파일 확장자 확인
        filename = file.filename
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in ['.json', '.csv']:
            return jsonify({'error': 'Unsupported file format. Use .json or .csv'}), 400
        
        # 파일 내용 읽기
        file_content = file.read().decode('utf-8')
        
        config_data = []
        
        if file_ext == '.json':
            # JSON 파일 파싱
            try:
                config_data = json.loads(file_content)
                if not isinstance(config_data, list):
                    return jsonify({'error': 'Invalid JSON format. Expected array of configuration objects'}), 400
                
                # 기존 형식을 새 형식으로 변환
                for config in config_data:
                    # 기존 필드가 있으면 새 필드로 변환
                    if 'limit_line_hi' in config:
                        config['line1'] = config.pop('limit_line_hi', '')
                        config['line1_color'] = '#FF0000'
                    if 'limit_line_lo' in config:
                        config['line2'] = config.pop('limit_line_lo', '')
                        config['line2_color'] = '#00FF00'
                    
                    # 새 필드들이 없으면 기본값 설정
                    if 'line1' not in config:
                        config['line1'] = ''
                        config['line1_color'] = '#FF0000'
                    if 'line2' not in config:
                        config['line2'] = ''
                        config['line2_color'] = '#00FF00'
                    if 'line3' not in config:
                        config['line3'] = ''
                        config['line3_color'] = '#0000FF'
                    if 'line4' not in config:
                        config['line4'] = ''
                        config['line4_color'] = '#FFFF00'
                    if 'line5' not in config:
                        config['line5'] = ''
                        config['line5_color'] = '#FF00FF'
                    if 'line6' not in config:
                        config['line6'] = ''
                        config['line6_color'] = '#00FFFF'
                    
                    # lo, hi 순서 변경
                    if 'hi' in config and 'lo' in config:
                        # 순서만 변경 (값은 그대로)
                        pass
                    elif 'hi' in config:
                        config['lo'] = ''
                    elif 'lo' in config:
                        config['hi'] = ''
                    else:
                        config['lo'] = ''
                        config['hi'] = ''
                        
            except json.JSONDecodeError as e:
                return jsonify({'error': f'Invalid JSON format: {str(e)}'}), 400
                
        elif file_ext == '.csv':
            # CSV 파일 파싱
            try:
                import csv
                import io
                
                csv_file = io.StringIO(file_content)
                csv_reader = csv.DictReader(csv_file)
                
                for row in csv_reader:
                    config_row = {
                        'parameter_name': row.get('Parameter Name', ''),
                        'description': row.get('Description', ''),
                        'type': row.get('Type', 'Raw'),
                        'formula': row.get('Formula', ''),
                        'custom_py': row.get('Custom (.py)', ''),
                        'hi': row.get('Hi', ''),
                        'lo': row.get('Lo', ''),
                        'limit_line_hi': row.get('Limit Line (Hi)', ''),
                        'limit_line_lo': row.get('Limit Line (Lo)', '')
                    }
                    config_data.append(config_row)
                    
            except Exception as e:
                return jsonify({'error': f'Error parsing CSV file: {str(e)}'}), 400
        
        # Config 파일의 파라미터 이름들 추출
        config_parameters = [config.get('parameter_name', '') for config in config_data if config.get('parameter_name')]
        
        # Database의 파라미터 목록 가져오기
        db_module = get_backend_module('db')
        db_parameters = db_module['get_parameters']()
        
        # Database에 있지만 Config 파일에 없는 파라미터들 찾기
        missing_parameters = [param for param in db_parameters if param not in config_parameters]
        
        # 누락된 파라미터들을 Config 데이터에 추가
        for param in missing_parameters:
            config_data.append({
                'parameter_name': param,
                'description': '',
                'type': 'Raw',
                'formula': '',
                'custom_py': '',
                'lo': '',
                'hi': '',
                'line1': '',
                'line1_color': '#FF0000',
                'line2': '',
                'line2_color': '#00FF00',
                'line3': '',
                'line3_color': '#0000FF',
                'line4': '',
                'line4_color': '#FFFF00',
                'line5': '',
                'line5_color': '#FF00FF',
                'line6': '',
                'line6_color': '#00FFFF'
            })
        
        logger.info(f"Successfully parsed config file with {len(config_data)} parameters")
        logger.info(f"Config file had {len(config_parameters)} parameters, added {len(missing_parameters)} missing parameters from database")
        
        return jsonify({
            'config_data': config_data,
            'config_parameters': config_parameters,
            'db_parameters': db_parameters,
            'missing_parameters': missing_parameters
        })
        
    except Exception as e:
        logger.error(f"Error uploading config file: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/save', methods=['POST'])
def save_config_file():
    """Configuration 데이터를 파일로 저장합니다."""
    try:
        data = request.get_json(silent=True)
        if not data or 'config_data' not in data:
            return jsonify({'error': 'No configuration data provided'}), 400
        
        config_data = data['config_data']
        if not isinstance(config_data, list):
            return jsonify({'error': 'Invalid configuration data format'}), 400
        
        # 사용자가 지정한 파일명 또는 기본 파일명 사용
        custom_filename = data.get('filename', '')
        if custom_filename:
            # 파일명에 .json 확장자가 없으면 추가
            if not custom_filename.endswith('.json'):
                custom_filename += '.json'
            filename = custom_filename
        else:
            # 기본 파일명 생성 (현재 시간 기준)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'config_{timestamp}.json'
        
        filepath = os.path.join(data_path, 'data', filename)
        
        # JSON 파일로 저장
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Configuration saved to: {filepath}")
        logger.info(f"Application path: {application_path}")
        logger.info(f"Data folder: {os.path.join(data_path, 'data')}")
        return jsonify({'success': True, 'filename': filename, 'filepath': filepath})
        
    except Exception as e:
        logger.error(f"Error saving config file: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/apply', methods=['POST'])
def apply_config():
    """Configuration을 적용합니다."""
    db_module = None # Initialize to avoid unbound variable warning
    def process_formula(formula):
        formula = (formula or '').strip()
        if not formula:
            return ''
        # 이미 result=로 시작하면 그대로, 아니면 자동으로 붙임
        if not re.match(r'^\s*result\s*=.*', formula, re.IGNORECASE):
            return f'result = {formula}'
        return formula

    try:
        data = request.get_json(silent=True)
        if not data or 'config_data' not in data:
            return jsonify({'error': 'No configuration data provided'}), 400
        
        config_data = data['config_data']
        if not isinstance(config_data, list):
            return jsonify({'error': 'Invalid configuration data format'}), 400
        
        # Configuration 데이터를 데이터베이스에 저장
        db_module = get_backend_module('db')
        derived_module = get_backend_module('derived')
        np = get_numpy()
        
        try:
            # Configuration 데이터 저장
            db_module['save_parameter_config'](config_data)
            
            # Derived 파라미터 생성
            for config in config_data:
                formula = process_formula(config.get('formula', ''))
                param_type = config.get('type', 'Raw')
                param_name = config.get('parameter_name', '')
                custom_py_content = config.get('custom_py_content', '')
                
                # Derived 파라미터 생성 (Formula 또는 Custom(.py) 사용)
                if param_type == 'Derived' and param_name:
                    if formula and not custom_py_content:
                        # Formula 사용
                        logger.info(f"Processing Derived parameter with formula: {param_name}")
                        logger.info(f"Formula: {formula}")
                        
                        # Formula에서 사용된 파라미터 추출 (함수명, 키워드 제외)
                        python_keywords = {'and', 'as', 'assert', 'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield', 'True', 'False', 'None'}
                        common_functions = {'result', 'np', 'mean', 'std', 'min', 'max', 'sum', 'len', 'abs', 'round', 'int', 'float', 'str', 'list', 'dict', 'set', 'tuple', 'range', 'enumerate', 'zip', 'map', 'filter', 'sorted', 'reversed', 'any', 'all', 'print', 'input', 'open', 'close', 'read', 'write', 'append', 'extend', 'insert', 'remove', 'pop', 'clear', 'copy', 'count', 'index', 'reverse', 'sort', 'keys', 'values', 'items', 'get', 'update', 'setdefault', 'popitem', 'clear', 'copy', 'fromkeys', 'add', 'discard', 'union', 'intersection', 'difference', 'symmetric_difference', 'issubset', 'issuperset', 'isdisjoint'}
                        
                        # 변수명 패턴으로 추출 (단, 키워드나 함수명 제외)
                        all_matches = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', formula)
                        used_params = []
                        for match in all_matches:
                            if (match not in python_keywords and 
                                match not in common_functions and 
                                not match.startswith('__') and  # 내장 속성 제외
                                match != param_name):  # 자기 자신 제외
                                used_params.append(match)
                        
                        logger.info(f"Extracted parameters from formula: {used_params}")
                        
                        # DB에 존재하는 파라미터만 사용
                        all_params = db_module['get_parameters']()
                        logger.info(f"Available parameters in DB: {all_params}")
                        used_params = [p for p in set(used_params) if p in all_params]
                        logger.info(f"Valid parameters for derived calculation: {used_params}")
                        
                        if used_params:
                            # 파라미터 데이터 준비
                            parameter_data = {}
                            for p in used_params:
                                param_data = db_module['get_timeseries_data'](p, -np.inf, np.inf)
                                if param_data and param_data['value']:
                                    parameter_data[p] = param_data['value']
                                    logger.info(f"Loaded data for parameter {p}: {len(param_data['value'])} points")
                            
                            if parameter_data:
                                try:
                                    logger.info(f"Executing derived parameter formula for {param_name}")
                                    result = derived_module['execute_derived_parameter'](formula, parameter_data)
                                    logger.info(f"Formula execution successful, result length: {len(result)}")
                                    
                                    # 기준 시간은 첫 번째 사용 파라미터의 time
                                    time_data = db_module['get_timeseries_data'](used_params[0], -np.inf, np.inf)['time']
                                    logger.info(f"Using time data from {used_params[0]}: {len(time_data)} points")
                                    
                                    # DB에 저장
                                    db_module['save_timeseries_data'](param_name, time_data, result, 0)
                                    logger.info(f"Successfully created derived parameter: {param_name}")
                                    
                                    # 저장 후 파라미터 목록 확인
                                    updated_params = db_module['get_parameters']()
                                    logger.info(f"Parameters after saving {param_name}: {updated_params}")
                                    
                                except Exception as e:
                                    logger.error(f"Error creating derived parameter {param_name}: {str(e)}")
                                    logger.error(traceback.format_exc())
                            else:
                                logger.warning(f"No valid parameter data found for derived parameter: {param_name}")
                        else:
                            logger.warning(f"No valid parameters found in formula for: {param_name}, formula: {formula}")
                    
                    elif custom_py_content and not formula:
                        # Custom(.py) 파일 사용
                        logger.info(f"Processing Derived parameter with custom .py file: {param_name}")
                        logger.info(f"Custom .py content length: {len(custom_py_content)}")
                        
                        try:
                            # Custom .py 파일에서 파라미터 추출
                            all_params = db_module['get_parameters']()
                            used_params = extract_parameters_from_custom_py(custom_py_content, all_params)
                            logger.info(f"Extracted parameters from custom .py: {used_params}")
                            
                            if used_params:
                                # 파라미터 데이터 준비
                                parameter_data = {}
                                for p in used_params:
                                    param_data = db_module['get_timeseries_data'](p, -np.inf, np.inf)
                                    if param_data and param_data['value']:
                                        parameter_data[p] = param_data['value']
                                        logger.info(f"Loaded data for parameter {p}: {len(param_data['value'])} points")
                                
                                if parameter_data:
                                    try:
                                        logger.info(f"Executing custom .py code for {param_name}")
                                        result = derived_module['execute_derived_parameter'](custom_py_content, parameter_data)
                                        logger.info(f"Custom .py execution successful, result length: {len(result)}")
                                        
                                        # 기준 시간은 첫 번째 사용 파라미터의 time
                                        time_data = db_module['get_timeseries_data'](used_params[0], -np.inf, np.inf)['time']
                                        logger.info(f"Using time data from {used_params[0]}: {len(time_data)} points")
                                        
                                        # DB에 저장
                                        db_module['save_timeseries_data'](param_name, time_data, result, 0)
                                        logger.info(f"Successfully created derived parameter from custom .py: {param_name}")
                                        
                                        # 저장 후 파라미터 목록 확인
                                        updated_params = db_module['get_parameters']()
                                        logger.info(f"Parameters after saving {param_name}: {updated_params}")
                                        
                                    except Exception as e:
                                        logger.error(f"Error creating derived parameter from custom .py {param_name}: {str(e)}")
                                        logger.error(traceback.format_exc())
                                else:
                                    logger.warning(f"No valid parameter data found for custom .py derived parameter: {param_name}")
                            else:
                                logger.warning(f"No valid parameters found in custom .py for: {param_name}")
                                
                        except Exception as e:
                            logger.error(f"Error processing custom .py file for {param_name}: {str(e)}")
                            logger.error(traceback.format_exc())
                    
                    elif formula and custom_py_content:
                        logger.warning(f"Both formula and custom .py content provided for {param_name}. Skipping.")
                    else:
                        logger.warning(f"No formula or custom .py content provided for derived parameter: {param_name}")
            
            logger.info(f"Applied configuration for {len(config_data)} parameters (including derived)")
            return jsonify({
                'success': True, 
                'message': f'Configuration applied to {len(config_data)} parameters',
                'refresh_parameters': True  # 파라미터 리스트 갱신을 위한 플래그 추가
            })
            
        except Exception as e:
            logger.error(f"Database error while applying config: {str(e)}")
            return jsonify({'error': f'Database error: {str(e)}'}), 500
        
    except Exception as e:
        logger.error(f"Error applying config: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/load', methods=['GET'])
def load_config():
    """현재 적용된 Configuration을 로드합니다."""
    db_module = None # Initialize to avoid unbound variable warning
    try:
        db_module = get_backend_module('db')
        config_data = db_module['load_parameter_config']()
        
        logger.info(f"Loaded configuration for {len(config_data)} parameters")
        return jsonify({'config_data': config_data})
        
    except Exception as e:
        logger.error(f"Error loading config: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/export_csv', methods=['POST'])
def export_config_csv():
    """Configuration을 CSV 파일로 내보냅니다."""
    try:
        data = request.get_json(silent=True) or {}
        config_data = data.get('config_data', [])
        
        if not config_data:
            return jsonify({'error': 'No configuration data to export'}), 400
        
        # CSV 헤더 정의
        headers = [
            'parameter_name', 'description', 'type', 'formula', 'custom_py',
            'lo', 'hi', 'line1', 'line2', 'line3', 'line4', 'line5', 'line6'
        ]
        
        # CSV 데이터 생성
        csv_data = []
        csv_data.append(','.join(headers))  # 헤더 추가
        
        for config in config_data:
            row = []
            for header in headers:
                value = config.get(header, '')
                # CSV에서 쉼표와 따옴표 처리
                if ',' in str(value) or '"' in str(value) or '\n' in str(value):
                    value = f'"{str(value).replace('"', '""')}"'
                row.append(str(value))
            csv_data.append(','.join(row))
        
        csv_content = '\n'.join(csv_data)
        
        # 파일명 생성 (현재 시간 포함)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'parameter_config_{timestamp}.csv'
        
        # 파일 저장
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(csv_content)
        
        logger.info(f"Exported configuration to CSV: {file_path}")
        
        return jsonify({
            'success': True,
            'message': 'Configuration exported to CSV successfully',
            'filename': filename,
            'file_path': file_path
        })
        
    except Exception as e:
        logger.error(f"Error exporting config to CSV: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/import_csv', methods=['POST'])
def import_config_csv():
    """CSV 파일에서 Configuration을 가져옵니다."""
    db_module = None # Initialize to avoid unbound variable warning
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'No file selected'}), 400
        
        filename = file.filename
        if not filename.endswith('.csv'):
            return jsonify({'error': 'File must be a CSV file'}), 400
        
        # 파일 내용을 바이트로 읽기
        file_bytes = file.read()
        
        # 여러 인코딩을 시도하여 CSV 파일 읽기
        encodings_to_try = ['utf-8', 'cp949', 'euc-kr', 'utf-8-sig', 'latin-1']
        csv_content = None
        
        for encoding in encodings_to_try:
            try:
                csv_content = file_bytes.decode(encoding)
                logger.info(f"Successfully decoded CSV file with encoding: {encoding}")
                break
            except UnicodeDecodeError as e:
                logger.warning(f"Failed to decode with {encoding}: {str(e)}")
                continue
        
        if csv_content is None:
            return jsonify({'error': 'Failed to decode CSV file. Please ensure the file is saved with UTF-8 encoding.'}), 400
        
        lines = csv_content.strip().split('\n')
        
        if len(lines) < 2:  # 헤더 + 최소 1개 데이터 행
            return jsonify({'error': 'CSV file must have at least header and one data row'}), 400
        
        # 헤더 파싱
        headers = [h.strip() for h in lines[0].split(',')]
        
        # 데이터 행 파싱
        config_data = []
        for line in lines[1:]:
            if not line.strip():
                continue
                
            # CSV 파싱 (쉼표와 따옴표 처리)
            values = []
            current_value = ''
            in_quotes = False
            
            for char in line:
                if char == '"':
                    in_quotes = not in_quotes
                elif char == ',' and not in_quotes:
                    values.append(current_value.strip())
                    current_value = ''
                else:
                    current_value += char
            
            values.append(current_value.strip())  # 마지막 값
            
            # 헤더와 값 매칭
            if len(values) >= len(headers):
                config = {}
                for i, header in enumerate(headers):
                    config[header] = values[i] if i < len(values) else ''
                config_data.append(config)
        
        # 데이터베이스 파라미터와 비교
        db_module = get_backend_module('db')
        db_parameters = db_module['get_parameters']()
        
        # CSV에 있는 파라미터 목록
        csv_parameters = [config.get('parameter_name', '') for config in config_data if config.get('parameter_name')]
        
        # CSV에 없지만 DB에 있는 파라미터 (누락된 파라미터)
        missing_parameters = [param for param in db_parameters if param not in csv_parameters]
        
        # CSV에 있지만 DB에 없는 파라미터 (Not in DB)
        not_in_db_parameters = [param for param in csv_parameters if param not in db_parameters]
        
        # 누락된 파라미터를 config_data에 추가
        for param in missing_parameters:
            config_data.append({
                'parameter_name': param,
                'description': '',
                'type': 'Raw',
                'formula': '',
                'custom_py': '',
                'lo': '',
                'hi': '',
                'line1': '',
                'line1_color': '#FF0000',
                'line2': '',
                'line2_color': '#00FF00',
                'line3': '',
                'line3_color': '#0000FF',
                'line4': '',
                'line4_color': '#FFFF00',
                'line5': '',
                'line5_color': '#FF00FF',
                'line6': '',
                'line6_color': '#00FFFF'
            })
        
        logger.info(f"Imported configuration from CSV: {len(config_data)} parameters")
        logger.info(f"Missing parameters from DB: {len(missing_parameters)}")
        logger.info(f"Parameters not in DB: {len(not_in_db_parameters)}")
        
        return jsonify({
            'success': True,
            'message': f'Configuration imported from CSV: {len(config_data)} parameters',
            'config_data': config_data,
            'missing_parameters': missing_parameters,
            'not_in_db_parameters': not_in_db_parameters,
            'config_parameters': csv_parameters,
            'db_parameters': db_parameters
        })
        
    except Exception as e:
        logger.error(f"Error importing config from CSV: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/uploads/<filename>')
def download_file(filename):
    """업로드된 파일을 다운로드합니다."""
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)
    except Exception as e:
        logger.error(f"Error downloading file {filename}: {str(e)}")
        return jsonify({'error': 'File not found'}), 404

def open_browser():
    webbrowser.open('http://127.0.0.1:9840/')

def extract_parameters_from_custom_py(custom_py_content, available_params):
    """
    Custom .py 파일 내용에서 사용된 파라미터를 추출합니다.
    """
    try:
        # Python 키워드와 함수명 제외
        python_keywords = {'and', 'as', 'assert', 'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield', 'True', 'False', 'None'}
        common_functions = {'result', 'np', 'mean', 'std', 'min', 'max', 'sum', 'len', 'abs', 'round', 'int', 'float', 'str', 'list', 'dict', 'set', 'tuple', 'range', 'enumerate', 'zip', 'map', 'filter', 'sorted', 'reversed', 'any', 'all', 'print', 'input', 'open', 'close', 'read', 'write', 'append', 'extend', 'insert', 'remove', 'pop', 'clear', 'copy', 'count', 'index', 'reverse', 'sort', 'keys', 'values', 'items', 'get', 'update', 'setdefault', 'popitem', 'clear', 'copy', 'fromkeys', 'add', 'discard', 'union', 'intersection', 'difference', 'symmetric_difference', 'issubset', 'issuperset', 'isdisjoint'}
        
        # 변수명 패턴으로 추출 (단, 키워드나 함수명 제외)
        all_matches = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', custom_py_content)
        used_params = []
        
        for match in all_matches:
            if (match not in python_keywords and 
                match not in common_functions and 
                not match.startswith('__') and  # 내장 속성 제외
                match in available_params):  # 사용 가능한 파라미터만
                used_params.append(match)
        
        # 중복 제거
        return list(set(used_params))
        
    except Exception as e:
        logger.error(f"Error extracting parameters from custom .py: {str(e)}")
        return []

if __name__ == '__main__':
    # 데이터베이스 초기화를 앱 시작 시점에 수행 (필수 초기화)
    initialize_database()
    Timer(1, open_browser).start()  # 1초 후 브라우저 열기
    try:
        app.run(debug=False, port=9840)  # 배포 시에는 debug=False로 설정, 포트 9840으로 변경
    finally:
        # 프로그램 종료 시 cleanup 실행
        cleanup_database()
        cleanup_upload_folder() 