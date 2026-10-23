# Offline Responses schema fixtures

These are hand-authored, synthetic structures derived from the official schemas,
not captures of operator/provider traffic. Every ID, timestamp and text/ciphertext
value is synthetic. No key, real response, reasoning or application source was used.

- `completed.json`: pinned GPT-5 nano plain-text response; documented zero cache
  writes; nullable metadata and optional `logprobs=null`.
- `nullable-metadata.json`: documented nullable service tier/background/config
  echoes. Actual request still fixes default tier, foreground execution and bounds.
- `incomplete.json`: terminal incomplete response with max-output reason, a
  partial reasoning item and fully accounted reasoning/output tokens.
- `reasoning.json`: documented summaries, reasoning text and ciphertext shapes;
  all are discarded and cannot reach the receipt or accounting artifacts.

Official generated types inspected October 23, 2026:

| Source in `openai/openai-python/src/openai/types` | Blob SHA |
| --- | --- |
| `responses/response.py` | `3ec1fd01f5230d7770db34ecdb442a5a70f5d6f4` |
| `responses/response_usage.py` | `33e8ac299f7a7ff67519805ea4899cafdd4d6cff` |
| `responses/response_reasoning_item.py` | `8744204522b660d0ec5bb1506ee2b983ba7b88de` |
| `responses/response_output_message.py` | `d041df641539525582f8e4ddcaa861bb88e81695` |
| `responses/response_output_text.py` | `e06f14279a2d92d4a28e9b452f52b6ae286e01f3` |
| `responses/response_output_refusal.py` | `54e727104f1694091fa3319c8e45f8f64ca7aa18` |
| `responses/response_status.py` | `4878564530a7c02ae566eb839957b3774a140403` |
| `responses/response_text_config.py` | `9e2eca238ec8c05af0b1da9090713745132c1d55` |
| `shared/reasoning.py` | `d3a642fad205fea19c861822f87298922bc49621` |
| `shared/metadata.py` | `854eb385b117f2cc17ffd8652a36316da7fea64f` |

These fixtures establish compatibility with the reviewed subset. They do not
prove that a live provider emits exactly these structures or diagnose a past
request whose raw response was deliberately not retained.
