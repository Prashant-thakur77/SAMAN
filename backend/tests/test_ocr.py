"""Reading a material's marking, and what that is worth (§5 camera input).

The feature reads the *marking*, not the part. A photograph cannot tell a 25 mm
bore from a 30 mm one, cannot see a seal type and cannot distinguish a Class 300
valve from a Class 600 one — the exact attributes the §2A veto layer decides on.
So the tests here are about text going into the existing engine, and about the
feature being honest when it cannot read.
"""

import io

import pytest

from app import ocr, ocr_eval

pytestmark = pytest.mark.skipif(
    not ocr.available(), reason="the OCR reader is not installed (make deps-ocr)"
)


def plate(text: str, size=(900, 260)) -> bytes:
    """A rendered nameplate.

    Always drawn at one base size and then scaled, so the lettering stays
    proportional to the frame however large the image is — which is what a
    photograph does. Drawing fixed-size text onto a bigger canvas instead makes
    the marking smaller as the file grows, which is a property of the fixture
    and not of any camera.
    """
    from PIL import Image, ImageDraw

    base = Image.new("RGB", (900, 260), "white")
    draw = ImageDraw.Draw(base)
    draw.rectangle([10, 10, 890, 250], outline="black", width=3)
    for index, line in enumerate(text.split("|")):
        draw.text((40, 40 + index * 44), line.strip(), fill="black")
    if size != (900, 260):
        base = base.resize(size, Image.LANCZOS)
    buffer = io.BytesIO()
    base.save(buffer, format="PNG")
    return buffer.getvalue()


class TestRepair:
    """Three conservative rules, each checked against what it must not touch."""

    def test_a_designation_split_in_half_is_rejoined(self):
        assert "6313" in ocr.repair("SKF BEARING BALL 63 13 2RS 2080 KG")

    def test_two_real_tokens_are_not_joined(self):
        """`6313 2RS` is a designation and a seal type, not a split."""
        assert ocr.repair("BALL 6313 2RS 2080 KG") == "BALL 6313 2RS 2080 KG"

    def test_a_letter_o_beside_a_digit_becomes_zero(self):
        assert ocr.repair("BEARING BALL 8O MM BORE 17OMM OD") == (
            "BEARING BALL 80 MM BORE 170MM OD"
        )

    def test_an_o_not_beside_a_digit_is_left_alone(self):
        """`FLO-GV01634` is a real part number and must survive."""
        assert "FLO-GV01634" in ocr.repair("THREADED FLOWSERVE FLO-GV01634")

    def test_a_long_word_run_together_with_digits_is_split(self):
        assert ocr.repair("GATE 300NB BUTTWELD51.1 BAR") == "GATE 300NB BUTTWELD 51.1 BAR"

    def test_a_short_prefix_is_not_split_from_its_digits(self):
        """Splitting `SS316` would destroy a material grade, and `SCH160` a pipe
        schedule — which costs more than the misreads the rule fixes."""
        repaired = ocr.repair("PIPE SEAMLESS 40NB SCH160 CS-A53 SS316")
        assert "SS316" in repaired and "SCH160" in repaired

    def test_two_words_run_together_are_split_when_both_are_known(self):
        """`GATEVALVE` costs the class assignment entirely, and with it every
        attribute — the classifier looks for `gate` and `valve` as tokens and
        finds neither."""
        assert ocr.repair("KITZ -GATEVALVE SIZE 32NB") == "KITZ -GATE VALVE SIZE 32NB"
        assert ocr.repair("BALLBEARING SKF 6205") == "BALL BEARING SKF 6205"

    def test_an_unknown_run_together_token_is_left_alone(self):
        """A generic alpha-alpha split is unsafe — nothing distinguishes a
        run-together phrase from a part number by shape. Both halves have to be
        words the taxonomy already knows."""
        assert ocr.repair("GASKETGARLOCK 25NB") == "GASKETGARLOCK 25NB"
        assert "FLO-GV01634" in ocr.repair("FLOWSERVE FLO-GV01634")

    def test_a_known_word_is_not_split_into_smaller_known_words(self):
        for word in ("SOCKETWELD", "BUTTWELD", "THREADED", "SEAMLESS"):
            assert ocr.repair(word) == word

    def test_it_leaves_a_clean_description_untouched(self):
        clean = "BOLT HEXAGON M16X2.0 100MM LENGTH GR 12.9 SS316 ZINC"
        assert ocr.repair(clean) == clean


class TestReading:
    def test_it_reads_a_stamped_marking(self):
        result = ocr.read(plate("SKF | 6205-2Z | MADE IN INDIA"))
        assert "6205-2Z" in result.text
        assert result.mean_confidence > 0.8
        assert result.seconds > 0

    def test_every_line_carries_its_own_confidence(self):
        result = ocr.read(plate("SKF | 6205-2Z"))
        assert result.lines
        for line in result.lines:
            assert 0.0 <= line.confidence <= 1.0
            assert line.uncertain == (line.confidence < ocr.LOW_CONFIDENCE)

    def test_a_blank_image_reads_as_nothing_rather_than_guessing(self):
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (400, 200), "white").save(buffer, format="PNG")
        assert ocr.read(buffer.getvalue()).text == ""

    def test_a_file_that_is_not_an_image_is_refused(self):
        with pytest.raises(ValueError, match="not an image"):
            ocr.read(b"legacy_code,description\nX,BEARING\n")

    def test_an_empty_upload_is_refused(self):
        with pytest.raises(ValueError, match="no image"):
            ocr.read(b"")

    def test_an_oversized_image_is_refused_before_it_is_decoded(self):
        with pytest.raises(ValueError, match="exceeds"):
            ocr.read(b"\x89PNG" + b"0" * (ocr.MAX_IMAGE_BYTES + 1))

    def test_a_large_photograph_is_downscaled_rather_than_refused(self):
        result = ocr.read(plate("SKF | 6205-2Z", size=(3200, 925)))
        assert "6205-2Z" in result.text

    def test_a_marking_too_small_to_read_reports_low_confidence(self):
        """The safety property that matters. Downscaling a photograph taken from
        across the room can destroy the lettering; what must not happen is a
        *confident* misread. Here the reader turns 6205-2Z into 6206-22 and says
        it is unsure, which is what the retake threshold acts on."""
        result = ocr.read(plate("SKF | 6205-2Z", size=(400, 116)))
        if "6205-2Z" not in result.text:
            assert result.mean_confidence < ocr_eval.RETAKE_BELOW


class TestScanEndpoint:
    def test_a_marking_resolves_through_the_ordinary_check(self, as_steward, pipeline_run):
        response = as_steward.post(
            "/api/smart-create/scan",
            files={"file": ("plate.png", plate("SKF | 6205-2Z"), "image/png")},
        )
        assert response.status_code == 200
        body = response.json()
        assert "6205-2Z" in body["ocr"]["text"]
        assert body["scanned"] is True
        # The photograph never reaches the matcher — only the text does.
        assert "probe" in body and body["probe"]["norm_text"]

    def test_an_illegible_image_says_so_instead_of_guessing(self, as_steward, pipeline_run):
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (400, 200), "white").save(buffer, format="PNG")
        body = as_steward.post(
            "/api/smart-create/scan",
            files={"file": ("blank.png", buffer.getvalue(), "image/png")},
        ).json()
        assert body["suggestions"] == []
        assert "legible" in body["recommendation"]["reason"]

    def test_a_non_image_is_a_400(self, as_steward, pipeline_run):
        response = as_steward.post(
            "/api/smart-create/scan",
            files={"file": ("notes.csv", b"a,b\n1,2\n", "text/csv")},
        )
        assert response.status_code == 400

    def test_a_viewer_cannot_scan(self, as_viewer):
        response = as_viewer.post(
            "/api/smart-create/scan",
            files={"file": ("plate.png", plate("SKF"), "image/png")},
        )
        assert response.status_code == 403

    def test_availability_is_reported_at_health(self, client):
        capabilities = client.get("/api/health").json()["capabilities"]
        assert capabilities["ocr"]["available"] is ocr.available()
        assert capabilities["ocr"]["engine"]


class TestMeasuredWorth:
    """§0.6: a camera feature without a number is a demo."""

    def test_a_clean_plate_usually_finds_its_material(self, db, pipeline_run):
        report = ocr_eval.evaluate(db, samples=8, conditions=("clean",))
        assert report["status"] == "measured"
        assert report["by_condition"]["clean"]["resolution_rate"] >= 0.6

    def test_the_readers_confidence_predicts_the_outcome(self, db, pipeline_run):
        """What makes the retake threshold honest rather than decorative: a
        clean plate is read confidently, an illegible one is not."""
        clean = ocr_eval.evaluate(db, samples=4, conditions=("clean",))
        severe = ocr_eval.evaluate(db, samples=4, conditions=("severe",))
        assert (
            clean["by_condition"]["clean"]["mean_ocr_confidence"]
            > severe["by_condition"]["severe"]["mean_ocr_confidence"]
        )

    def test_an_illegible_plate_returns_nothing_rather_than_something_wrong(
        self, db, pipeline_run
    ):
        """The failure mode that matters: it must not resolve confidently to the
        wrong material."""
        report = ocr_eval.evaluate(db, samples=5, conditions=("severe",))
        severe = report["by_condition"]["severe"]
        assert severe["resolution_rate"] == 0.0
        assert severe["read_nothing"] == severe["scanned"]

    def test_the_retake_threshold_sits_where_the_measurement_put_it(self):
        assert ocr_eval.RETAKE_BELOW == 0.90

    def test_the_report_states_what_it_does_not_measure(self, db, pipeline_run):
        report = ocr_eval.evaluate(db, samples=2, conditions=("clean",))
        assert "photographed" in report["note"]
