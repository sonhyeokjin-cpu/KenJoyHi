import unittest

import numpy as np

from backend.bit_extractor import extract_bits_array, resolve_sign_bit_index


def encode_directional_bits(value, lsb, end_bit):
    """Place a directional bit sequence into its source-word bit positions."""
    width = abs(end_bit - lsb) + 1
    unsigned = value & ((1 << width) - 1)
    positions = range(lsb, end_bit + 1) if end_bit >= lsb else range(lsb, end_bit - 1, -1)
    word = 0
    for output_bit, source_bit in enumerate(positions):
        if unsigned & (1 << output_bit):
            word |= 1 << source_bit
    return word


def extract_signed(word, lsb, msb, data_format):
    sign_bit = resolve_sign_bit_index(lsb, msb, data_format)
    width = abs(sign_bit - lsb) + 1
    result = int(extract_bits_array(np.array([word]), lsb, sign_bit, data_format)[0])
    return result - (1 << width) if result & (1 << (width - 1)) else result


class BitExtractorSignedRangeTests(unittest.TestCase):
    def test_ascending_range_uses_bit_after_msb(self):
        self.assertEqual(resolve_sign_bit_index(1, 10, '32bit'), 11)
        word = encode_directional_bits(-3, 1, 11)
        self.assertEqual(extract_signed(word, 1, 10, '32bit'), -3)

    def test_descending_range_uses_bit_before_msb(self):
        self.assertEqual(resolve_sign_bit_index(10, 1, '32bit'), 0)
        word = encode_directional_bits(-3, 10, 0)
        self.assertEqual(extract_signed(word, 10, 1, '32bit'), -3)

    def test_original_descending_a429_case_no_longer_requires_max_index(self):
        self.assertEqual(resolve_sign_bit_index(28, 13, '32bit'), 12)

    def test_1553_ui_zero_to_thirteen_maps_to_physical_sign_bit_one(self):
        # Frontend maps 1553B UI indexes with physical = 15 - UI.
        physical_lsb, physical_msb = 15 - 0, 15 - 13
        self.assertEqual((physical_lsb, physical_msb), (15, 2))
        self.assertEqual(resolve_sign_bit_index(physical_lsb, physical_msb, '16bit'), 1)

    def test_signed_range_rejects_a_sign_bit_outside_word(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            resolve_sign_bit_index(0, 31, '32bit')
        with self.assertRaisesRegex(ValueError, 'outside'):
            resolve_sign_bit_index(15, 0, '16bit')


if __name__ == '__main__':
    unittest.main()
