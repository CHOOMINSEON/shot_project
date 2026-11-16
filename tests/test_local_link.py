from studio import storage


def test_linked_asset_reads_original_location(tmp_path):
    (tmp_path / 'assets' / 'a').mkdir(parents=True)
    (tmp_path / 'assets' / 'b').mkdir(parents=True)
    source = tmp_path / '내 영상' / '리뷰.mp4'
    source.parent.mkdir()
    source.write_bytes(b'x')
    (tmp_path / 'assets' / 'a' / 'source.path').write_text(str(source), encoding='utf-8')
    assert storage.asset_file(tmp_path, 'a') == source
    assert storage.asset_file(tmp_path, 'b') == tmp_path / 'assets' / 'b' / 'original'
