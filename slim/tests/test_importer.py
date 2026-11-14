from jukebox import importer
from jukebox.config import load_cards
from jukebox.cli import main


def make_v2(tmp_path):
    sc = tmp_path / "shared" / "shortcuts"
    af = tmp_path / "shared" / "audiofolders"
    sc.mkdir(parents=True); af.mkdir(parents=True)
    (tmp_path / "settings").mkdir()
    (sc / "0123456789").write_text("Good-Night\r\n")
    (af / "Good-Night").mkdir(); (af / "Good-Night" / "spotify.txt").write_text("spotify:user:me:playlist:ABC123\n")
    (sc / "AABB").write_text("Pumuckl")
    (af / "Pumuckl").mkdir(); (af / "Pumuckl" / "01.mp3").write_text("x")
    (sc / "0000000001").write_text("0000000001")                      # never assigned
    (sc / "0000000002").write_text("Radio")
    (af / "Radio").mkdir(); (af / "Radio" / "livestream.txt").write_text("http://x")
    (sc / "0000000003").write_text("Gone")                            # folder not copied
    (sc / "0000000004").write_text("Link")
    (af / "Link").mkdir(); (af / "Link" / "spotify.txt").write_text("https://open.spotify.com/album/XYZ9?si=abc")
    (tmp_path / "settings" / "rfid_trigger_play.conf").write_text(
        'CMDVOLUP="1111111111"\nCMDVOL50="2222222222"\nCMDNEXT="%CMDNEXT%"\nCMDRANDCARD="3333333333"\n#CMDSTOP="9"\n')
    return tmp_path


def test_convert(tmp_path):
    res = importer.convert(make_v2(tmp_path))
    by = {e.id: e for e in res.entries}
    assert by["0123456789"].play == "spotify:playlist:ABC123"
    assert by["AABB"].play == "folder:Pumuckl"
    assert by["0000000004"].play == "spotify:album:XYZ9"
    assert by["1111111111"].action == "volume_up"
    assert by["2222222222"].action == "volume_set" and by["2222222222"].args == {"value": 50}
    assert "0000000001" in res.unused
    reasons = dict(res.skipped)
    assert "livestream" in reasons["0000000002"]
    assert "not found" in reasons["0000000003"]
    assert "no equivalent" in reasons["3333333333"]
    assert "CMDSTOP" not in {e.name for e in res.entries}


def test_cli_apply_roundtrip(tmp_path, capsys):
    src = make_v2(tmp_path / "v2")
    cfg = tmp_path / "config.toml"; cfg.write_text("")
    assert main(["-c", str(cfg), "import-v2", str(src)]) == 0
    assert not (tmp_path / "cards.toml").exists()                     # dry run
    assert main(["-c", str(cfg), "import-v2", str(src), "--apply"]) == 0
    cards = load_cards(tmp_path / "cards.toml")
    assert cards["2222222222"].args == {"value": 50}
    assert cards["0123456789"].play == "spotify:playlist:ABC123"
    capsys.readouterr()
    main(["-c", str(cfg), "import-v2", str(src), "--apply"])           # second run adds nothing
    assert "0 new" in capsys.readouterr().out
    assert len(load_cards(tmp_path / "cards.toml")) == len(cards)


def test_normalize():
    assert importer.normalize_spotify("spotify:playlist:AB1") == "spotify:playlist:AB1"
    assert importer.normalize_spotify("nonsense") is None
