from app.wecom.handler import _chat_id, _message_text, _user_id


def test_extract_wecom_message_fields():
    frame = {
        "body": {
            "from": {"userid": "alice"},
            "chatid": "room-1",
            "text": {"content": "hello Holmes"},
        }
    }
    assert _user_id(frame) == "alice"
    assert _chat_id(frame) == "room-1"
    assert _message_text(frame) == "hello Holmes"
