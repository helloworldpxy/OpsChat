# -*- coding: utf-8 -*-
"""
API 密钥加密存储
- 使用 Fernet（对称加密）对落库的 API 密钥加密
- 加密密钥来源：环境变量 SECRET_KEY > data/.secret_key 文件（自动生成并持久化）
- 保证同一台机器重启后仍可解密；不同机器/不同 SECRET_KEY 无法解密
"""

import os
import logging
from pathlib import Path
from functools import lru_cache

logger = logging.getLogger(__name__)

_FERNET = None


def _load_or_create_secret_key() -> bytes:
    """从环境变量或持久化文件加载密钥；均不存在时生成并持久化"""
    env_key = os.environ.get("SECRET_KEY", "")
    if env_key:
        return env_key.encode("utf-8")

    key_file = Path("data") / ".secret_key"
    try:
        if key_file.exists():
            raw = key_file.read_text(encoding="utf-8").strip()
            if raw:
                return raw.encode("utf-8")
    except Exception as e:
        logger.warning(f"读取密钥文件失败: {e}")

    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(key.decode("utf-8"), encoding="utf-8")
        # 收紧权限（POSIX 下仅属主可读）
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        logger.info("已生成持久化加密密钥 data/.secret_key")
    except Exception as e:
        logger.warning(f"持久化加密密钥失败（本次运行内有效）: {e}")
    return key


@lru_cache(maxsize=1)
def _get_fernet():
    """获取（缓存的）Fernet 实例"""
    from cryptography.fernet import Fernet
    key = _load_or_create_secret_key()
    return Fernet(_derive_key(key))


def _derive_key(raw: bytes) -> bytes:
    """将任意长度密钥派生为 Fernet 所需的 32 字节 urlsafe base64"""
    import base64
    import hashlib
    digest = hashlib.sha256(raw).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plaintext: str) -> str:
    """加密明文密钥，返回密文字符串；明文为空时原样返回空串"""
    if not plaintext:
        return ""
    try:
        return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.warning(f"密钥加密失败: {e}")
        return ""


def decrypt_secret(ciphertext: str) -> str:
    """解密密钥密文，返回明文；密文为空返回空串；解密失败返回空串并告警"""
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception:
        # 兼容历史明文（加密功能启用前已落库的密钥）
        logger.warning("密钥解密失败，可能是未加密的历史数据（将按明文返回）或 SECRET_KEY 变更")
        return ciphertext
