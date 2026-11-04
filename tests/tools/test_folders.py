from ultron.tools.folders import execute_plan, list_folder, plan_organize, to_trash, undo_plan


def setup_dir(tmp_path):
    d = tmp_path / "Downloads"
    d.mkdir()
    (d / "a.pdf").write_text("pdf")
    (d / "b.png").write_text("png")
    (d / "c.xyz").write_text("xyz")
    (d / "pasta").mkdir()
    return d


def test_list_folder(tmp_path):
    names = {e["name"]: e["is_dir"] for e in list_folder(setup_dir(tmp_path))}
    assert names == {"a.pdf": False, "b.png": False, "c.xyz": False, "pasta": True}


def test_plan_categorizes_files_and_skips_dirs(tmp_path):
    d = setup_dir(tmp_path)
    plan = plan_organize(tmp_path / "home", d)
    dsts = {m.src.split("/")[-1].split("\\")[-1]: m.dst for m in plan.moves}
    assert len(plan.moves) == 3
    assert dsts["a.pdf"].replace("\\", "/").endswith("Documentos/a.pdf")
    assert dsts["b.png"].replace("\\", "/").endswith("Imagens/b.png")
    assert dsts["c.xyz"].replace("\\", "/").endswith("Outros/c.xyz")
    assert (d / "pasta").is_dir() and (d / "a.pdf").exists()  # plano não move nada


def test_execute_never_overwrites(tmp_path):
    d = setup_dir(tmp_path)
    (d / "Documentos").mkdir()
    (d / "Documentos" / "a.pdf").write_text("antigo")
    home = tmp_path / "home"
    plan = plan_organize(home, d)
    execute_plan(home, plan.id)
    assert (d / "Documentos" / "a.pdf").read_text() == "antigo"
    assert (d / "Documentos" / "a (1).pdf").read_text() == "pdf"
    assert (d / "Imagens" / "b.png").exists()


def test_undo_restores(tmp_path):
    d = setup_dir(tmp_path)
    home = tmp_path / "home"
    plan = plan_organize(home, d)
    execute_plan(home, plan.id)
    undo_plan(home, plan.id)
    assert (d / "a.pdf").read_text() == "pdf"
    assert (d / "b.png").exists() and (d / "c.xyz").exists()


def test_execute_unknown_plan(tmp_path):
    assert "não encontrado" in execute_plan(tmp_path, "deadbeef").lower()


def test_to_trash_moves_not_deletes(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("dado")
    home = tmp_path / "home"
    dst = to_trash(home, f)
    assert not f.exists() and dst.read_text() == "dado"
    assert dst.parent == home / "Lixeira"
    f.write_text("dado2")
    dst2 = to_trash(home, f)
    assert dst2 != dst and dst.exists()
