from PIL import Image, ImageDraw
import os
import sqlite3
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = 'data/timeseries.db'

# Create a 32x32 image with a white background
img = Image.new('RGB', (32, 32), 'white')
draw = ImageDraw.Draw(img)

# Draw a simple chart icon
draw.line([(4, 24), (28, 24)], fill='black', width=2)  # x-axis
draw.line([(4, 4), (4, 24)], fill='black', width=2)    # y-axis
draw.line([(4, 20), (8, 16), (12, 18), (16, 12), (20, 14), (24, 8), (28, 10)], fill='blue', width=2)  # chart line

# Save as ICO
if not os.path.exists('static'):
    os.makedirs('static')
img.save('static/favicon.ico', format='ICO')

def debug_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    try:
        # VM004_G 파라미터의 ID 확인
        c.execute("SELECT id FROM parameters WHERE name = 'VM004_G'")
        param_id = c.fetchone()
        logging.info(f"VM004_G parameter ID: {param_id}")
        
        # 해당 파라미터의 timeseries 데이터 확인
        c.execute("SELECT level, COUNT(*) FROM timeseries WHERE parameter_id = ? GROUP BY level", (param_id[0],))
        timeseries = c.fetchall()
        logging.info(f"VM004_G timeseries data: {timeseries}")
        
    except Exception as e:
        logging.error(f"Error debugging database: {str(e)}")
    finally:
        conn.close()

def save_timeseries_data(param_name, time_data, value_data, level):
    logger.info(f"Saving timeseries data for {param_name} (level {level})")
    logger.info(f"Time data shape: {time_data.shape}, Value data shape: {value_data.shape}")
    logger.info(f"Time data sample: {time_data[:5]}")
    logger.info(f"Value data sample: {value_data[:5]}")
    # ... 나머지 코드 ... 

def get_timeseries_data(param_name, start_time, end_time, level):
    logger.info(f"Fetching data for {param_name} (level {level})")
    logger.info(f"Time range: {start_time} to {end_time}")
    # ... 나머지 코드 ... 