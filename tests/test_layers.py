import pytest

from studio import timeline

ASSETS = {'v': {'status': 'ready', 'metadata': {'duration': 10, 'has_video': True}},
          'm': {'status': 'ready', 'metadata': {'duration': 5, 'has_video': False}}}


def state(**layer):
    base = {'id': 'l1', 'track': 1, 'asset_id': 'v', 'start': 1, 'end': 4, 'at': 2}
    return {'clips': [{'id': 'c', 'asset_id': 'v', 'start': 0, 'end': 10}], 'layers': [{**base, **layer}]}


def test_valid_layers_are_frame_aligned():
    s = timeline.validate_state(state(at=2.0101), ASSETS)
    assert s['layers'][0]['at'] == pytest.approx(2.0)


@pytest.mark.parametrize('bad', [{'track': 0}, {'track': 6}, {'end': 11}, {'at': -1}, {'asset_id': 'x'}, {'volume': 3}])
def test_invalid_layers_are_rejected(bad):
    with pytest.raises(ValueError):
        timeline.validate_state(state(**bad), ASSETS)


def test_layers_in_group_range_are_shifted_and_trimmed():
    s = {'layers': [{'id': 'a', 'track': 2, 'asset_id': 'm', 'start': 0, 'end': 5, 'at': 3},
                    {'id': 'b', 'track': 1, 'asset_id': 'v', 'start': 1, 'end': 4, 'at': 20}]}
    out = timeline.layers_in(s, 4, 10)
    assert len(out) == 1 and out[0]['at'] == 0 and out[0]['start'] == 1 and out[0]['end'] == 5


def test_render_signature_changes_with_layers():
    a = {'clips': [], 'layers': []}
    b = {'clips': [], 'layers': [{'id': 'x'}]}
    assert timeline.render_signature(a) != timeline.render_signature(b)
