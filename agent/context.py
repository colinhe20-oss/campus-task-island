"""只保留结果截断；暂不启用模型摘要和持久记忆。"""


def truncate_observation(text: str, max_chars: int = 12000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n[已截断，原文共 {len(text)} 字符]"
