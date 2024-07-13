import spacy
from word2number import w2n


def extract_ids_from_text(text: str, nlp_model: spacy.Language) -> dict[str, int | None]:
    doc = nlp_model(text)
    object_units: dict[str, int | None] = {
        "playlist": None,
        "device": None,
    }

    for token in doc:
        if token.pos_ == "NUM":
            try:
                number = w2n.word_to_num(token.text)
            except ValueError:
                try:
                    number = int(token.text)
                except ValueError:
                    continue  # Skip if the number conversion fails

            next_token = doc[token.i - 1] if token.i - 1 < len(doc) else None
            if next_token and next_token.text.lower() in ["playlist", "playlists"]:
                object_units["playlist"] = number
            elif next_token and next_token.text.lower() in ["device", "devices"]:
                object_units["device"] = number

    return object_units
