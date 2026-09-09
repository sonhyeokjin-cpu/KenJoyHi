import numpy as np
import logging
import traceback
from .db import save_timeseries_data, get_timeseries_data

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def extract_bits(value, lsb, msb, data_format='32bit'):
    """
    정수 값에서 지정된 비트 범위를 추출합니다.
    
    Parameters:
    -----------
    value : int
        비트를 추출할 정수 값
    lsb : int
        최하위 비트 인덱스 (사용자 입력)
    msb : int
        최상위 비트 인덱스 (사용자 입력)
    data_format : str
        데이터 포맷 ('32bit' 또는 '16bit')
    
    Returns:
    --------
    int
        추출된 비트 값
    """
    try:
        # 데이터 포맷에 따른 최대 비트 수 설정
        max_bits = 32 if data_format == '32bit' else 16
        
        # 실제 비트 범위 계산 (사용자 입력 순서와 무관)
        start_bit = min(lsb, msb)
        end_bit = max(lsb, msb)
        
        # 비트 마스크 생성
        mask = ((1 << (end_bit - start_bit + 1)) - 1) << start_bit
        
        # 비트 추출
        extracted = (value & mask) >> start_bit
        
        # LSB > MSB인 경우 비트 시퀀스를 역순으로 처리
        if lsb > msb:
            # 비트 수 계산
            bit_count = end_bit - start_bit + 1
            # 비트 시퀀스 역순으로 변환
            reversed_bits = 0
            for i in range(bit_count):
                if extracted & (1 << i):
                    reversed_bits |= (1 << (bit_count - 1 - i))
            extracted = reversed_bits
        
        logger.info(f"Bit extraction: value={value}, lsb={lsb}, msb={msb}, start_bit={start_bit}, end_bit={end_bit}, extracted={extracted}")
        
        return extracted
        
    except Exception as e:
        logger.error(f"Error extracting bits: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def apply_sign_bit(value, bit_width):
    """
    추출된 값에 대해 최상위 비트를 부호 비트로 해석하여 2의 보수 변환을 적용합니다.
    """
    sign_bit = (value >> (bit_width - 1)) & 1
    if sign_bit:
        return value - (1 << bit_width)
    else:
        return value

def apply_lsb_scale(value, lsb_scale):
    """
    LSB 스케일을 적용합니다.
    
    Parameters:
    -----------
    value : int
        스케일을 적용할 값
    lsb_scale : float
        LSB 스케일 값
    
    Returns:
    --------
    float
        스케일이 적용된 값
    """
    try:
        scaled_value = value * lsb_scale
        logger.info(f"Applied LSB scale {lsb_scale}: {value} -> {scaled_value}")
        return scaled_value
        
    except Exception as e:
        logger.error(f"Error applying LSB scale: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def create_bit_extracted_parameter(source_parameter, lsb, msb, data_format='32bit', 
                                 sign_bit_index=None, lsb_scale=1.0, parameter_name=None):
    """
    소스 파라미터에서 비트를 추출하여 새로운 파라미터를 생성합니다.
    
    Parameters:
    -----------
    source_parameter : str
        소스 파라미터 이름
    lsb : int
        최하위 비트 인덱스
    msb : int
        최상위 비트 인덱스
    data_format : str
        데이터 포맷 ('32bit' 또는 '16bit')
    sign_bit_index : int, optional
        부호 비트 인덱스 (None이면 부호 없음)
    lsb_scale : float
        LSB 스케일 값
    parameter_name : str, optional
        생성할 파라미터 이름 (없으면 자동 생성)
    
    Returns:
    --------
    tuple
        (생성된 파라미터 이름, 진행상황 정보)
    """
    try:
        logger.info(f"Creating bit extracted parameter from {source_parameter}")
        logger.info(f"Parameters: lsb={lsb}, msb={msb}, format={data_format}, sign_bit={sign_bit_index}, scale={lsb_scale}, parameter_name={parameter_name}")
        
        # 소스 데이터 가져오기
        source_data = get_timeseries_data(source_parameter, -np.inf, np.inf)
        if not source_data or not source_data['time'] or not source_data['value']:
            raise ValueError(f"No data available for source parameter: {source_parameter}")
        
        time_data = np.array(source_data['time'], dtype=np.float64)
        value_data = np.array(source_data['value'], dtype=np.int64)  # 정수형으로 변환
        
        logger.info(f"Source data statistics:")
        logger.info(f"  Time array: min={np.min(time_data)}, max={np.max(time_data)}, len={len(time_data)}")
        logger.info(f"  Value array: min={np.min(value_data)}, max={np.max(value_data)}, mean={np.mean(value_data):.6f}, std={np.std(value_data):.6f}")
        
        # 각 데이터 포인트에 대해 비트 추출 수행
        extracted_values = []
        total_points = len(value_data)
        progress_step = max(1, total_points // 100)  # 100단계로 진행상황 표시
        
        logger.info(f"Starting bit extraction for {total_points} data points")
        
        progress_info = {
            'total_points': total_points,
            'processed_points': 0,
            'progress_percentage': 0.0
        }
        
        for i, value in enumerate(value_data):
            try:
                # 비트 추출
                extracted = extract_bits(int(value), lsb, msb, data_format)
                
                # 부호 비트 적용 (sign_bit_index가 MSB와 같을 때만, bit width 사용)
                bit_width = abs(msb - lsb) + 1
                if sign_bit_index is not None and sign_bit_index == max(lsb, msb):
                    extracted = apply_sign_bit(extracted, bit_width)
                
                # LSB 스케일 적용
                extracted = apply_lsb_scale(extracted, lsb_scale)
                
                extracted_values.append(extracted)
                
                # 진행상황 업데이트
                progress_info['processed_points'] = i + 1
                progress_info['progress_percentage'] = (i + 1) / total_points * 100
                
                # 진행상황 로깅 (100단계마다)
                if i % progress_step == 0 or i == total_points - 1:
                    logger.info(f"Bit extraction progress: {progress_info['progress_percentage']:.1f}% ({i + 1}/{total_points})")
                
            except Exception as e:
                logger.error(f"Error processing value {value} at index {i}: {str(e)}")
                extracted_values.append(0.0)  # 에러 시 0으로 설정
        
        extracted_values = np.array(extracted_values, dtype=np.float64)
        
        # 새로운 파라미터 이름 생성
        if parameter_name:
            new_parameter_name = parameter_name
        else:
            # LSB와 MSB의 순서에 관계없이 항상 작은 값부터 큰 값 순으로 표시
            min_bit = min(lsb, msb)
            max_bit = max(lsb, msb)
            direction_suffix = '_rev' if lsb > msb else ''
            param_suffix = f"_bit{min_bit}_{max_bit}{direction_suffix}"
            if sign_bit_index is not None:
                param_suffix += f"_sign{sign_bit_index}"
            if lsb_scale != 1.0:
                param_suffix += f"_scale{lsb_scale}"
            new_parameter_name = f"{source_parameter}{param_suffix}"
        
        # 데이터베이스에 저장
        save_timeseries_data(new_parameter_name, time_data, extracted_values, 0)
        
        # 최종 진행상황 (100%)
        progress_info['processed_points'] = total_points
        progress_info['progress_percentage'] = 100.0
        
        logger.info(f"Successfully created bit extracted parameter: {new_parameter_name}")
        logger.info(f"Extracted data statistics:")
        logger.info(f"  Extracted array: min={np.min(extracted_values)}, max={np.max(extracted_values)}, mean={np.mean(extracted_values):.6f}, std={np.std(extracted_values):.6f}")
        
        return new_parameter_name, progress_info
        
    except Exception as e:
        logger.error(f"Error creating bit extracted parameter: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def get_bit_extractor_info(source_parameter, lsb, msb, data_format='32bit', 
                          sign_bit_index=None, lsb_scale=1.0):
    """
    BIT Extractor 정보를 반환합니다.
    
    Parameters:
    -----------
    source_parameter : str
        소스 파라미터 이름
    lsb : int
        최하위 비트 인덱스
    msb : int
        최상위 비트 인덱스
    data_format : str
        데이터 포맷 ('32bit' 또는 '16bit')
    sign_bit_index : int, optional
        부호 비트 인덱스
    lsb_scale : float
        LSB 스케일 값
    
    Returns:
    --------
    dict
        BIT Extractor 정보
    """
    try:
        # 실제 비트 범위 계산
        start_bit = min(lsb, msb)
        end_bit = max(lsb, msb)
        is_reverse = lsb > msb
        
        # 비트 범위 설명
        if is_reverse:
            bit_range_desc = f"비트 {lsb}부터 {msb}까지 역순으로 추출 (실제 범위: {start_bit}-{end_bit})"
        else:
            bit_range_desc = f"비트 {lsb}부터 {msb}까지 순차적으로 추출 (실제 범위: {start_bit}-{end_bit})"
        
        # 수식 설명
        if is_reverse:
            formula = f"extract_bits_reverse(value, {lsb}, {msb})"
        else:
            formula = f"extract_bits(value, {lsb}, {msb})"
        
        # 부호 비트 적용 설명
        if sign_bit_index is not None:
            formula += f" → apply_sign_bit(extracted, {sign_bit_index})"
            bit_range_desc += f", 부호 비트: {sign_bit_index}"
        
        # LSB 스케일 적용 설명
        if lsb_scale != 1.0:
            formula += f" → apply_lsb_scale(result, {lsb_scale})"
            bit_range_desc += f", LSB 스케일: {lsb_scale}"
        
        # 주파수 응답 정보 (필터와 유사한 형태로 제공)
        frequency_response = {
            'type': 'bit_extraction',
            'parameters': {
                'source_parameter': source_parameter,
                'lsb': lsb,
                'msb': msb,
                'data_format': data_format,
                'is_reverse': is_reverse,
                'actual_range': f"{start_bit}-{end_bit}",
                'sign_bit_index': sign_bit_index,
                'lsb_scale': lsb_scale
            }
        }
        
        return {
            'formula': formula,
            'description': f"소스 파라미터 '{source_parameter}'에서 {bit_range_desc}",
            'parameters': {
                'source_parameter': source_parameter,
                'lsb': lsb,
                'msb': msb,
                'data_format': data_format,
                'sign_bit_index': sign_bit_index,
                'lsb_scale': lsb_scale,
                'is_reverse': is_reverse,
                'actual_bit_range': f"{start_bit}-{end_bit}"
            },
            'frequency_response': frequency_response
        }
        
    except Exception as e:
        logger.error(f"Error getting bit extractor info: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def test_bit_extractor():
    """
    BIT Extractor 기능을 테스트합니다.
    """
    try:
        logger.info("Testing BIT Extractor functionality...")
        
        # 테스트 데이터
        test_value = 0b1010110011010101  # 16비트 테스트 값
        
        # 1. 기본 비트 추출 테스트
        logger.info(f"Testing basic bit extraction from {test_value} (binary: {bin(test_value)})")
        
        # 비트 3-7 추출 (11010 = 26)
        # 0b1010110011010101에서 비트 3-7은 11010 (26)
        extracted = extract_bits(test_value, 3, 7, '16bit')
        expected = 26
        assert extracted == expected, f"Expected {expected}, got {extracted}"
        logger.info(f"✓ Bit extraction 3-7: {extracted} (expected: {expected})")
        
        # 비트 0-3 추출 (0101 = 5)
        # 0b1010110011010101에서 비트 0-3은 0101 (5)
        extracted = extract_bits(test_value, 0, 3, '16bit')
        expected = 5
        assert extracted == expected, f"Expected {expected}, got {extracted}"
        logger.info(f"✓ Bit extraction 0-3: {extracted} (expected: {expected})")
        
        # 비트 8-11 추출 (1100 = 12)
        extracted = extract_bits(test_value, 8, 11, '16bit')
        expected = 12
        assert extracted == expected, f"Expected {expected}, got {extracted}"
        logger.info(f"✓ Bit extraction 8-11: {extracted} (expected: {expected})")
        
        # 2. 부호 비트 테스트
        logger.info("Testing sign bit application...")
        
        # 양수 테스트 (부호 비트 0)
        test_positive = 0b00010110  # 22 (부호 비트 0)
        signed = apply_sign_bit(test_positive, 7)
        expected = 22
        assert signed == expected, f"Expected {expected}, got {signed}"
        logger.info(f"✓ Positive value with sign bit 0: {signed} (expected: {expected})")
        
        # 음수 테스트 (부호 비트 1)
        test_negative = 0b10010110  # 부호 비트 1, 나머지 22
        signed = apply_sign_bit(test_negative, 7)
        expected = -106
        assert signed == expected, f"Expected {expected}, got {signed}"
        logger.info(f"✓ Negative value with sign bit 1: {signed} (expected: {expected})")
        
        # 3. LSB 스케일 테스트
        logger.info("Testing LSB scale application...")
        
        test_value = 10
        scaled = apply_lsb_scale(test_value, 0.5)
        expected = 5.0
        assert scaled == expected, f"Expected {expected}, got {scaled}"
        logger.info(f"✓ LSB scale 0.5: {scaled} (expected: {expected})")
        
        # 4. 복합 테스트
        logger.info("Testing combined operations...")
        
        # 비트 추출 + 부호 비트 + 스케일
        complex_value = 0b11010110  # 부호 비트 1, 나머지 86
        extracted = extract_bits(complex_value, 0, 6, '16bit')  # 86
        signed = apply_sign_bit(extracted, 6)  # -86
        scaled = apply_lsb_scale(signed, 0.1)  # -8.6
        expected = -4.2
        assert abs(scaled - expected) < 1e-6, f"Expected {expected}, got {scaled}"
        logger.info(f"✓ Complex operation: {scaled} (expected: {expected})")
        
        logger.info("✓ All BIT Extractor tests passed!")
        return True
        
    except Exception as e:
        logger.error(f"BIT Extractor test failed: {str(e)}")
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    # 모듈이 직접 실행될 때 테스트 실행
    test_bit_extractor() 