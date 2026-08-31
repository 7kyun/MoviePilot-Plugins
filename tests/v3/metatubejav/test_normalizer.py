import pytest

from metatubejav.normalizer import normalize_code


@pytest.mark.parametrize(
    ("filename", "expected"),
    (
        ("@Milan@ty999.me_SONE-509_6K-C.mp4", "SONE-509"),
        ("SONE-509_6K-C", "SONE-509"),
        ("[98t.tv]vema-181-4k-C.mp4", "VEMA-181"),
        ("ABP-030-C-c_c-C-Cd1-cd4.mp4", "ABP-030"),
        ("caribbean-020317_001.mp4", "020317_001"),
        ("FC2-PPV-123456-C.mp4", "FC2-123456"),
        ("Tokyo Hot n9001 FHD.mp4", "N9001"),
    ),
)
def test_normalize_code_matches_metatube_number_trim(filename: str, expected: str) -> None:
    """验证插件番号清理与 MetaTube SDK 规则一致。"""
    assert normalize_code(filename) == expected
