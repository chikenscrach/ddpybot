from utils.constants import mag_color, mag_emoji


def test_mag_color_thresholds():
    assert mag_color(6.5) == 0xE74C3C  # 紅
    assert mag_color(5.5) == 0xE67E22  # 橘
    assert mag_color(4.5) == 0xF1C40F  # 黃
    assert mag_color(3.5) == 0x2ECC71  # 綠
    assert mag_color(2.0) == 0x3498DB  # 藍


def test_mag_color_boundaries():
    """臨界值屬於高一級的顏色"""
    assert mag_color(6.0) == 0xE74C3C
    assert mag_color(5.0) == 0xE67E22
    assert mag_color(4.0) == 0xF1C40F
    assert mag_color(3.0) == 0x2ECC71


def test_mag_emoji():
    assert mag_emoji(6.0) == "🔴"
    assert mag_emoji(5.0) == "🟠"
    assert mag_emoji(4.0) == "🟡"
    assert mag_emoji(3.0) == "🟢"
    assert mag_emoji(1.0) == "🔵"
