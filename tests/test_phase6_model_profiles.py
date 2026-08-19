# -*- coding: utf-8 -*-
"""
阶段六测试：模型管理（多模型配置档案）
覆盖 /api/settings/models 的增删改查、激活切换运行时、密钥只写不读
"""

import pytest

from backend.config import settings
from backend.core.agent import agent
from backend.core.model_profiles import seed_default_profile_if_empty, apply_active_model_profile
from backend.models.model_profile import ModelProfile, is_valid_profile_id


@pytest.fixture(autouse=True)
def restore_llm_state():
    """快照并恢复 settings 与 agent.llm_client 的运行时配置"""
    snap = (settings.llm_api_key, settings.llm_base_url, settings.llm_model)
    client = agent.llm_client
    client_snap = (client.api_key, client.base_url, client.model)
    yield
    settings.llm_api_key, settings.llm_base_url, settings.llm_model = snap
    client.update_config(*client_snap)


class TestModelProfileModel:
    def test_is_valid_profile_id(self):
        assert is_valid_profile_id("deepseek")
        assert is_valid_profile_id("my-gateway_2")
        assert not is_valid_profile_id("")
        assert not is_valid_profile_id("bad id")
        assert not is_valid_profile_id("bad/id")
        assert not is_valid_profile_id("a" * 65)


class TestSeedAndApply:
    def test_seed_from_env(self):
        seed_default_profile_if_empty()
        from backend.database import SessionLocal
        db = SessionLocal()
        try:
            profile = db.query(ModelProfile).filter(ModelProfile.is_active.is_(True)).first()
        finally:
            db.close()
        # 由 conftest 环境变量种子化（deepseek + test-key）
        assert profile is not None
        assert profile.base_url  # 非空

    def test_seed_is_noop_when_exists(self, client):
        from backend.database import SessionLocal
        db = SessionLocal()
        try:
            before = db.query(ModelProfile).count()
        finally:
            db.close()
        seed_default_profile_if_empty()
        db = SessionLocal()
        try:
            after = db.query(ModelProfile).count()
        finally:
            db.close()
        assert before == after

    def test_apply_active_profile(self, client):
        from backend.database import SessionLocal
        db = SessionLocal()
        try:
            active = db.query(ModelProfile).filter(ModelProfile.is_active.is_(True)).first()
        finally:
            db.close()
        profile = apply_active_model_profile()
        assert profile is not None
        assert settings.llm_model == (active.active_model if active else settings.llm_model)


class TestModelsAPI:
    def test_list_models_seeded_and_masked(self, client):
        resp = client.get("/api/settings/models")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        profiles = body["data"]["profiles"]
        assert len(profiles) >= 1
        assert "catalog" in body["data"]
        assert "deepseek" in body["data"]["catalog"]
        # 密钥只写不读：任何档案不返回 api_key 明文
        raw = resp.text
        assert "test-key" not in raw
        for p in profiles:
            assert "api_key" not in p
            assert "api_key_set" in p

    def test_create_and_delete(self, client):
        resp = client.post("/api/settings/models", json={
            "id": "p6-gw",
            "name": "P6 网关",
            "base_url": "https://gw.p6.test/v1",
            "api_key": "sk-p6-secret-xyz",
            "models": ["p6-large", "p6-small"],
            "active_model": "p6-large",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "sk-p6-secret-xyz" not in resp.text
        assert body["data"]["api_key_set"] is True
        assert body["data"]["is_active"] is False

        # 重复 ID → 409
        dup = client.post("/api/settings/models", json={
            "id": "p6-gw", "name": "重复", "base_url": "https://x/v1", "models": ["m1"],
        })
        assert dup.status_code == 409

        # 非法 ID → 400
        bad = client.post("/api/settings/models", json={
            "id": "bad/id", "name": "x", "base_url": "https://x/v1", "models": ["m1"],
        })
        assert bad.status_code == 400

        # 无模型 → 400
        nom = client.post("/api/settings/models", json={
            "id": "p6-nomodel", "name": "x", "base_url": "https://x/v1", "models": [],
        })
        assert nom.status_code == 400

        # 删除
        dele = client.delete("/api/settings/models/p6-gw")
        assert dele.status_code == 200
        gone = client.delete("/api/settings/models/p6-gw")
        assert gone.status_code == 404

    def test_update_keeps_key_when_blank(self, client):
        client.post("/api/settings/models", json={
            "id": "p6-keepkey", "name": "Keep", "base_url": "https://k.test/v1",
            "api_key": "sk-keep-key-123", "models": ["m1"],
        })
        resp = client.put("/api/settings/models/p6-keepkey", json={
            "name": "Keep 改名",
            "base_url": "https://k2.test/v1",
            "models": ["m1", "m2"],
            "active_model": "m2",
        })
        assert resp.status_code == 200
        assert "sk-keep-key-123" not in resp.text

        # 激活后运行时使用更新后的 base_url / active_model，密钥仍沿用
        act = client.post("/api/settings/models/p6-keepkey/activate")
        assert act.status_code == 200
        assert settings.llm_base_url == "https://k2.test/v1"
        assert settings.llm_model == "m2"
        assert agent.llm_client.base_url == "https://k2.test/v1"
        assert agent.llm_client.model == "m2"
        assert agent.llm_client.api_key == "sk-keep-key-123"

        client.delete("/api/settings/models/p6-keepkey")

    def test_activate_switches_runtime_and_clears_others(self, client):
        client.post("/api/settings/models", json={
            "id": "p6-a", "name": "A", "base_url": "https://a.test/v1",
            "api_key": "sk-a", "models": ["ma"],
        })
        client.post("/api/settings/models", json={
            "id": "p6-b", "name": "B", "base_url": "https://b.test/v1",
            "api_key": "sk-b", "models": ["mb"],
        })

        act_a = client.post("/api/settings/models/p6-a/activate")
        assert act_a.status_code == 200
        assert settings.llm_base_url == "https://a.test/v1"
        assert settings.llm_model == "ma"

        act_b = client.post("/api/settings/models/p6-b/activate")
        assert act_b.status_code == 200
        assert settings.llm_base_url == "https://b.test/v1"
        assert settings.llm_model == "mb"

        # 仅一个激活
        listing = client.get("/api/settings/models").json()["data"]["profiles"]
        active = [p for p in listing if p["is_active"]]
        assert len(active) == 1
        assert active[0]["id"] == "p6-b"

        client.delete("/api/settings/models/p6-a")
        client.delete("/api/settings/models/p6-b")

    def test_delete_active_falls_back(self, client):
        # 激活后删除，接口应正常返回，且运行时配置保留最后值
        client.post("/api/settings/models", json={
            "id": "p6-active", "name": "Active", "base_url": "https://active.test/v1",
            "api_key": "sk-active", "models": ["ma"],
        })
        client.post("/api/settings/models/p6-active/activate")
        resp = client.delete("/api/settings/models/p6-active")
        assert resp.status_code == 200
        gone = client.get("/api/settings/models").json()["data"]["profiles"]
        assert all(p["id"] != "p6-active" for p in gone)
        # 运行时仍持有最后应用的配置
        assert settings.llm_base_url == "https://active.test/v1"
        assert settings.llm_model == "ma"

    def test_test_profile_without_key(self, client):
        client.post("/api/settings/models", json={
            "id": "p6-nokey", "name": "NoKey", "base_url": "https://nokey.test/v1",
            "models": ["m1"],
        })
        resp = client.post("/api/settings/models/p6-nokey/test")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "API Key" in body["message"]
        client.delete("/api/settings/models/p6-nokey")