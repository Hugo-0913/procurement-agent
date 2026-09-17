from procurement_agent.db.models import init_db, seed_demo_data
from procurement_agent.erp.repository import ErpRepository


def make_repo(tmp_path) -> ErpRepository:
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    return ErpRepository(engine)


def test_exact_name_matches(tmp_path):
    assert make_repo(tmp_path).find_material_by_name("A4 纸").sku == "ST-A4-500"


def test_name_without_space_matches(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("A4纸") is not None


def test_alias_with_extra_word_matches(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("A4 复印纸") is not None
    assert repo.find_material_by_name("A4复印纸") is not None


def test_full_width_space_matches(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("A4\u3000纸") is not None


def test_sku_matches(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("ST-A4-500") is not None


def test_different_spec_does_not_match(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("A5 纸") is None
    assert repo.find_material_by_name("订书机") is None


def test_blank_input_returns_none(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("") is None
    assert repo.find_material_by_name(None) is None


def test_alias_from_master_data_matches(tmp_path):
    """主数据里的别名应能命中：用户说"办公用纸"、"复印纸"都要能对上 A4 纸。"""
    repo = make_repo(tmp_path)
    for text in ("办公用纸", "复印纸", "打印纸", "A4纸"):
        material = repo.find_material_by_name(text)
        assert material is not None, f"别名未命中: {text}"
        assert material.sku == "ST-A4-500"


def test_extra_words_with_alias_still_match(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.find_material_by_name("普通办公用纸（白）") is not None
