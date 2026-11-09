import numpy as np
from PIL import Image, ImageDraw

from pinmass.matching import (Matcher, MatchSettings, allowed_ranges, color_match,
                              extract_palette, look_similarity, signature)

GREY, BLACK, RED, BLUE, WHITE = (128, 128, 128), (10, 10, 10), (220, 20, 30), (30, 60, 220), (250, 250, 250)


def stripes(parts, size=120):
    """Vertical bands: parts = [(rgb, share), ...]."""
    im = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(im)
    x = 0
    for rgb, share in parts:
        w = round(share * size)
        d.rectangle([x, 0, x + w, size], fill=rgb)
        x += w
    return im


REF = stripes([(GREY, 0.6), (BLACK, 0.25), (RED, 0.15)])


def test_palette_finds_main_colors_and_shares():
    pal = extract_palette(REF)
    assert len(pal.shares) == 3
    assert abs(pal.shares[0] - 0.6) < 0.05
    assert np.allclose(pal.shares.sum(), 1)
    assert tuple(pal.rgb[0]) == (128, 128, 128) or np.abs(pal.rgb[0].astype(int) - 128).max() < 6


def test_strict_tolerance_needs_same_amounts():
    pal = extract_palette(REF)
    same = stripes([(GREY, 0.58), (BLACK, 0.27), (RED, 0.15)])
    shifted = stripes([(GREY, 0.2), (BLACK, 0.2), (RED, 0.6)])
    assert color_match(pal, same, 0).ok
    assert not color_match(pal, shifted, 0).ok


def test_loose_tolerance_allows_any_amounts_of_the_same_colors():
    pal = extract_palette(REF)
    shifted = stripes([(GREY, 0.2), (BLACK, 0.2), (RED, 0.6)])
    assert color_match(pal, shifted, 100).ok


def test_loose_tolerance_still_rejects_other_colors():
    pal = extract_palette(REF)
    blue = stripes([(BLUE, 0.7), (WHITE, 0.3)])
    assert not color_match(pal, blue, 100).ok


def test_loose_tolerance_still_needs_each_main_color_present():
    pal = extract_palette(REF)
    no_red = stripes([(GREY, 0.7), (BLACK, 0.3)])
    assert not color_match(pal, no_red, 100).ok


def test_ranges_widen_with_tolerance():
    pal = extract_palette(REF)
    tight = allowed_ranges(pal, 0)[0]
    loose = allowed_ranges(pal, 100)[0]
    assert tight[1] - tight[0] < loose[1] - loose[0]


def checker(n, size=120, color=(255, 255, 255), bg=(0, 0, 0)):
    im = Image.new("RGB", (size, size), bg)
    d = ImageDraw.Draw(im)
    s = size // n
    for i in range(n):
        for j in range(n):
            if (i + j) % 2:
                d.rectangle([i * s, j * s, (i + 1) * s, (j + 1) * s], fill=color)
    return im


def test_look_similarity_ranks_resized_copy_above_unrelated():
    ref = checker(6)
    copy = ref.resize((300, 300))
    other = Image.new("RGB", (120, 120), (200, 180, 90))
    ImageDraw.Draw(other).ellipse([20, 20, 100, 100], fill=(40, 90, 30))
    s_ref = signature(ref)
    assert look_similarity(s_ref, signature(copy)) > 90
    assert look_similarity(s_ref, signature(copy)) > look_similarity(s_ref, signature(other)) + 20


def test_matcher_scores_bytes(tmp_path):
    ref_path = tmp_path / "ref.png"
    REF.save(ref_path)
    m = Matcher(MatchSettings(reference=str(ref_path), look=True, colors=True))
    import io
    buf = io.BytesIO()
    REF.save(buf, "JPEG")
    sc = m.score(buf.getvalue())
    assert sc.color.ok and sc.combined > 85
    assert m.select([("same", sc)])[0][0] == "same"
    assert m.score(b"not an image") is None


def test_picked_colors_without_a_reference():
    from pinmass.matching import Palette
    pal = Palette.from_entries([("#dc141e", 1.0)]).plus("#0a0a0a")
    assert np.allclose(pal.shares, [0.5, 0.5])
    s = MatchSettings(colors=True, palette=pal.entries())
    assert s.active
    m = Matcher(s)
    import io
    good, bad = io.BytesIO(), io.BytesIO()
    stripes([(RED, 0.5), (BLACK, 0.5)]).save(good, "PNG")
    stripes([(BLUE, 1.0)]).save(bad, "PNG")
    assert m.score(good.getvalue()).color.ok
    assert not m.score(bad.getvalue()).color.ok
    assert len(pal.without(0).shares) == 1


def test_look_alone_needs_a_reference():
    assert not MatchSettings(look=True).active


def test_look_cutoff_is_relative_to_the_pool(tmp_path):
    from pinmass.matching import Score
    ref_path = tmp_path / "ref.png"
    REF.save(ref_path)
    m = Matcher(MatchSettings(reference=str(ref_path), look=True, closeness=50))
    pool = [(i, Score(look=50 + i * 0.2)) for i in range(100)]  # 50..69.8
    kept = m.select(pool)
    assert 20 <= len(kept) <= 45                  # roughly the top third
    assert kept[0][0] == 99                       # best first
    low = [(i, Score(look=30 + i * 0.1)) for i in range(100)]  # all under the floor
    assert m.select(low) == []
