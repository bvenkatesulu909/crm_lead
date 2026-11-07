"""Cutting a streamed answer into cleaned sentences (ADR 0023, step VM1). Pure, no database."""

from app.modules.assistant.guardrails import MAX_OUTPUT_CHARS, SAFE_OUTPUT
from app.modules.assistant.sentences import SentenceStream


def feed_all(*pieces: str) -> tuple[list[str], SentenceStream]:
    stream = SentenceStream()
    out: list[str] = []
    for piece in pieces:
        out.extend(stream.feed(piece))
    out.extend(stream.flush())
    return out, stream


def test_a_sentence_is_sent_as_soon_as_it_ends() -> None:
    stream = SentenceStream()
    assert stream.feed("Your ticket ") == []
    assert stream.feed("is open. It was ") == ["Your ticket is open."]
    assert stream.feed("opened today") == []
    assert stream.flush() == ["It was opened today"]


def test_question_marks_exclamations_and_line_breaks_end_a_sentence() -> None:
    out, _ = feed_all("Hello! Do you mean ", "Asha? Yes.\nNext line")
    assert out == ["Hello!", "Do you mean Asha?", "Yes.", "Next line"]


def test_a_full_stop_inside_a_word_or_number_does_not_end_the_sentence() -> None:
    out, _ = feed_all("The total is 1.5 lakh for crm.example.com users. Done")
    assert out == ["The total is 1.5 lakh for crm.example.com users.", "Done"]


def test_a_link_split_over_two_pieces_is_still_removed() -> None:
    # Cleaned piece by piece, "[click](https://evil.example/" + "steal?x=1). Then" would leak.
    out, _ = feed_all("See [click here](https://evil.ex", "ample/steal?d=secret). Then more.")
    joined = " ".join(out)
    assert "evil.example" not in joined
    assert "steal" not in joined
    assert "Then more." in joined


def test_no_sentence_is_cut_while_a_link_bracket_is_open() -> None:
    stream = SentenceStream()
    # The ". " is inside the link text: nothing may be sent until the link is closed.
    assert stream.feed("Read [the guide. Part one](https://x.example/a") == []
    out = stream.feed(") now. ")
    assert len(out) == 1
    assert "x.example" not in out[0]


def test_an_image_is_removed() -> None:
    out, _ = feed_all("Here ![chart](https://tracker.example/p.png?leak=1) is it. ")
    assert "tracker.example" not in " ".join(out)


def test_a_link_inside_the_crm_stays() -> None:
    out, _ = feed_all("Open [the lead](/leads/1234). ")
    assert "/leads/1234" in out[0]


def test_a_secret_marker_stops_the_stream_with_the_safe_answer() -> None:
    stream = SentenceStream()
    first = stream.feed("Fine so far. The database is postgres://u:p@h/db. More text. ")
    assert first == ["Fine so far.", SAFE_OUTPUT]
    assert stream.blocked
    assert stream.feed("Even more. ") == []
    assert stream.flush() == []


def test_blank_pieces_send_nothing() -> None:
    out, _ = feed_all("", "   ", "\n\n")
    assert out == []


def test_an_answer_longer_than_the_cap_is_cut_not_refused() -> None:
    stream = SentenceStream()
    sent = stream.feed("word " * (MAX_OUTPUT_CHARS // 5 + 10))
    assert len(sent) == 1
    assert len(sent[0]) <= MAX_OUTPUT_CHARS
    assert stream.full
    assert not stream.blocked
    assert stream.feed("more. ") == []
    assert stream.flush() == []


def test_a_stray_bracket_does_not_hold_back_the_whole_answer() -> None:
    stream = SentenceStream()
    assert stream.feed("Status (open. ") == []  # waits a little for the bracket
    out = stream.feed("More words here. " * 50)
    assert out and out[0].startswith("Status (open.")


def test_a_half_written_address_cut_by_the_hold_limit_is_still_removed() -> None:
    long_tail = "a" * 700
    out, _ = feed_all(f"See [x](https://evil.example/{long_tail}. Next. ")
    assert "evil.example" not in " ".join(out)
