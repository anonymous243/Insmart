import base64
import json
from datetime import datetime

def encode_cursor(created_at: datetime, id: int) -> str:
    cursor_dict = {
        "created_at": created_at.isoformat(),
        "id": id
    }
    json_str = json.dumps(cursor_dict)
    return base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")

def decode_cursor(cursor_str: str) -> tuple[datetime, int]:
    try:
        json_str = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        cursor_dict = json.loads(json_str)
        created_at = datetime.fromisoformat(cursor_dict["created_at"])
        return created_at, cursor_dict["id"]
    except Exception as e:
        raise ValueError("Invalid cursor format") from e
