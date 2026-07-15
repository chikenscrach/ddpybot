from services.earthquake_api import get_max_intensity, group_shaking_areas


def _quake(areas):
    return {"Intensity": {"ShakingArea": areas}}


def test_max_intensity_empty():
    assert get_max_intensity(_quake([])) == "—"
    assert get_max_intensity({}) == "—"


def test_max_intensity_picks_highest():
    quake = _quake([
        {"AreaIntensity": "2級", "CountyName": "臺北市"},
        {"AreaIntensity": "5弱", "CountyName": "花蓮縣"},
        {"AreaIntensity": "4級", "CountyName": "宜蘭縣"},
    ])
    assert get_max_intensity(quake) == "5弱"


def test_group_shaking_areas_sorted_desc():
    quake = _quake([
        {"AreaIntensity": "2級", "CountyName": "臺北市"},
        {"AreaIntensity": "4級", "CountyName": "花蓮縣"},
        {"AreaIntensity": "2級", "CountyName": "新北市"},
    ])
    grouped = group_shaking_areas(quake)
    assert grouped[0] == ("4級", ["花蓮縣"])
    assert grouped[1][0] == "2級"
    assert sorted(grouped[1][1]) == ["新北市", "臺北市"]


def test_group_shaking_areas_splits_multi_county():
    """「、」分隔的多縣市要拆開並去重"""
    quake = _quake([
        {"AreaIntensity": "3級", "CountyName": "臺北市、新北市"},
        {"AreaIntensity": "3級", "CountyName": "新北市"},
    ])
    grouped = group_shaking_areas(quake)
    assert grouped == [("3級", ["新北市", "臺北市"])]
