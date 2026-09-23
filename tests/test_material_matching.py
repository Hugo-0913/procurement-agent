from procurement_agent.db.models import init_db, seed_demo_data
from procurement_agent.erp.repository import ErpRepository


def make_repo(tmp_path) -> ErpRepository:
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    return ErpRepository(engine)


def test_exact_name_matches(tmp_path):
    assert make_repo(tmp_path).find_material_by_name("一次性无菌注射器").sku == "ST-SYR-5ML"


def test_name_without_space_matches(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("注射器") is not None


def test_alias_with_extra_word_matches(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("A4 无菌注射器") is not None
    assert repo.find_material_by_name("无菌注射器") is not None


def test_full_width_space_matches(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("一次性无菌\u3000注射器") is not None


def test_sku_matches(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("ST-SYR-5ML") is not None


def test_different_spec_does_not_match(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("输液器") is None
    assert repo.find_material_by_name("呼吸机") is None


def test_blank_input_returns_none(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("") is None
    assert repo.find_material_by_name(None) is None


def test_alias_from_master_data_matches(tmp_path):
    """主数据里的别名应能命中：用户说"无菌注射器"、"无菌注射器"都要能对上 一次性无菌注射器。"""
    repo = make_repo(tmp_path)
    for text in ("无菌注射器", "无菌注射器", "注射器", "注射器"):
        material = repo.find_material_by_name(text)
        assert material is not None, f"别名未命中: {text}"
        assert material.sku == "ST-SYR-5ML"


def test_extra_words_with_alias_still_match(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("一次性无菌注射器（5ml）") is not None
