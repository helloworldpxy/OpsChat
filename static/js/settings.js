/**
 * 设置功能模块
 * 处理模型管理（多模型档案）与安全设置
 */

const Settings = {
    /**
     * 初始化设置模块
     */
    init() {
        this.bindEvents();
        this.bindSettingsNav();
        this.loadSettings();
        this.initModelProfiles();
    },

    /**
     * 绑定事件
     */
    bindEvents() {
        // 安全设置开关
        const securityToggles = ['enableGuardrail', 'enableInputSanitizer', 'enableOutputValidator', 'enableSandbox'];
        securityToggles.forEach(id => {
            const toggle = document.getElementById(id);
            if (toggle) {
                toggle.addEventListener('change', () => this.saveSystemConfig());
            }
        });

        // ===== 模型管理（多模型配置） =====
        const addModelBtn = document.getElementById('addModelBtn');
        if (addModelBtn) addModelBtn.addEventListener('click', () => this.openModelForm());

        const mpCatalog = document.getElementById('mpCatalog');
        if (mpCatalog) mpCatalog.addEventListener('change', () => this.onCatalogChange());

        const mpAddModelBtn = document.getElementById('mpAddModelBtn');
        if (mpAddModelBtn) mpAddModelBtn.addEventListener('click', () => this.addModelRow());

        const mpSave = document.getElementById('mpSave');
        if (mpSave) mpSave.addEventListener('click', () => this.saveModelProfile());

        const mpCancel = document.getElementById('mpCancel');
        if (mpCancel) mpCancel.addEventListener('click', () => this.closeModelForm());

        const mpClose = document.getElementById('modelFormClose');
        if (mpClose) mpClose.addEventListener('click', () => this.closeModelForm());

        const mpToggleKey = document.getElementById('mpToggleKey');
        if (mpToggleKey) {
            mpToggleKey.addEventListener('click', () => {
                const input = document.getElementById('mpApiKey');
                const label = mpToggleKey.querySelector('span');
                if (input.type === 'password') {
                    input.type = 'text';
                    if (label) label.textContent = '隐藏';
                } else {
                    input.type = 'password';
                    if (label) label.textContent = '显示';
                }
            });
        }

        document.querySelectorAll('[data-close-model]').forEach(el => {
            el.addEventListener('click', () => this.closeModelForm());
        });

        const mpModelList = document.getElementById('mpModelList');
        if (mpModelList) {
            mpModelList.addEventListener('click', (e) => {
                const rm = e.target.closest('.btn-remove-model');
                if (rm) {
                    rm.closest('.model-id-row').remove();
                    this.refreshActiveModelOptions();
                }
            });
            mpModelList.addEventListener('input', () => this.refreshActiveModelOptions());
        }
    },

    /**
     * 设置页导航：模型 / 安全 / 关于
     */
    bindSettingsNav() {
        const items = document.querySelectorAll('.settings-nav-item');
        const panes = document.querySelectorAll('#page-settings .settings-section[data-pane]');
        items.forEach(item => {
            item.addEventListener('click', () => {
                items.forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                const section = item.dataset.section;
                panes.forEach(p => {
                    p.style.display = p.dataset.pane === section ? '' : 'none';
                });
            });
        });
    },

    /**
     * 加载设置
     */
    async loadSettings() {
        try {
            const result = await API.getSettings();

            if (result.success) {
                const { security } = result.data;

                // 设置安全配置
                if (security) {
                    document.getElementById('enableGuardrail').checked = security.enable_security_guardrail;
                    document.getElementById('enableInputSanitizer').checked = security.enable_input_sanitizer;
                    document.getElementById('enableOutputValidator').checked = security.enable_output_validator;
                    document.getElementById('enableSandbox').checked = security.enable_sandbox;
                }
            }

        } catch (error) {
            console.error('加载设置失败:', error);
        }
    },

    /**
     * 保存系统配置
     */
    async saveSystemConfig() {
        const config = {
            enable_security_guardrail: document.getElementById('enableGuardrail').checked,
            enable_input_sanitizer: document.getElementById('enableInputSanitizer').checked,
            enable_output_validator: document.getElementById('enableOutputValidator').checked,
            enable_sandbox: document.getElementById('enableSandbox').checked,
        };

        try {
            await API.saveSystemConfig(config);

        } catch (error) {
            console.error('保存系统配置失败:', error);
        }
    },

    // ==================== 模型管理（多模型配置档案） ====================

    /**
     * 初始化模型管理
     */
    async initModelProfiles() {
        this.catalog = {};
        await this.loadModelProfiles();
    },

    /**
     * 加载模型档案列表
     */
    async loadModelProfiles() {
        try {
            const result = await API.listModelProfiles();
            if (result.success) {
                this.catalog = result.data.catalog || {};
                this.renderModelProfiles(result.data.profiles || []);
            } else {
                const el = document.getElementById('modelProfileEmpty');
                if (el) el.textContent = '加载失败';
            }
        } catch (error) {
            console.error('加载模型档案失败:', error);
            const el = document.getElementById('modelProfileEmpty');
            if (el) el.textContent = '加载失败: ' + error.message;
        }
    },

    /**
     * 渲染模型档案卡片列表
     */
    renderModelProfiles(profiles) {
        const list = document.getElementById('modelProfileList');
        if (!list) return;
        if (!profiles.length) {
            list.innerHTML = '<div class="empty-hint">还没有模型档案，点击「添加模型」开始。</div>';
            return;
        }
        list.innerHTML = profiles.map(p => this.modelProfileCardHtml(p)).join('');
        list.querySelectorAll('[data-act]').forEach(btn => {
            btn.addEventListener('click', () => {
                this.onCardAction(btn.dataset.act, btn.closest('.model-profile-card').dataset.id);
            });
        });
    },

    /**
     * 单张模型档案卡片 HTML
     */
    modelProfileCardHtml(p) {
        const custom = !(this.catalog && this.catalog[p.id]);
        const chips = (p.models || []).map(m =>
            `<span class="mp-model-chip${m === p.active_model ? ' active' : ''}">${this.escapeHtml(m)}</span>`
        ).join('') || '<span class="mp-card-muted">无模型</span>';
        return `
            <div class="model-profile-card${p.is_active ? ' active' : ''}" data-id="${this.escapeHtml(p.id)}">
                <div class="mp-card-head">
                    <span class="mp-card-name">${this.escapeHtml(p.name)}</span>
                    <span class="mp-card-id">${this.escapeHtml(p.id)}</span>
                    ${custom ? '<span class="mp-card-tag">自定义</span>' : ''}
                    ${p.is_active ? '<span class="mp-card-badge">使用中</span>' : ''}
                </div>
                <div class="mp-card-url" title="${this.escapeHtml(p.base_url)}">${this.escapeHtml(p.base_url)}</div>
                <div class="mp-card-models">${chips}</div>
                <div class="mp-card-key">
                    ${p.api_key_set
                        ? '<span class="key-dot configured" title="API Key 已配置"></span><span>已配置</span>'
                        : '<span class="key-dot missing" title="API Key 未配置"></span><span>未配置密钥</span>'}
                    <span class="mp-card-active-model">当前：${this.escapeHtml(p.active_model || '-')}</span>
                </div>
                <div class="mp-card-actions">
                    ${p.is_active ? '' : '<button class="btn btn-primary btn-sm" data-act="activate">使用</button>'}
                    <button class="btn btn-secondary btn-sm" data-act="test">测试</button>
                    <button class="btn btn-secondary btn-sm" data-act="edit">编辑</button>
                    <button class="btn btn-danger btn-sm" data-act="delete">删除</button>
                </div>
            </div>`;
    },

    /**
     * HTML 转义（防 XSS）
     */
    escapeHtml(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    },

    /**
     * 卡片操作分发：使用 / 测试 / 编辑 / 删除
     */
    async onCardAction(act, id) {
        if (act === 'activate') {
            const r = await API.activateModelProfile(id);
            if (r.success) {
                App.showNotification(r.message, 'success');
                this.loadModelProfiles();
            } else {
                App.showNotification('操作失败: ' + (r.message || r.detail), 'error');
            }
        } else if (act === 'test') {
            const r = await API.testModelProfile(id);
            if (r && r.success) {
                App.showNotification('API连接成功', 'success');
            } else {
                App.showNotification((r && r.message) || 'API连接失败', 'error');
            }
        } else if (act === 'edit') {
            const r = await API.listModelProfiles();
            const p = (r.data.profiles || []).find(x => x.id === id);
            if (p) this.openModelForm(p);
        } else if (act === 'delete') {
            App.showConfirm('确定删除该模型档案？', '删除后无法恢复（API Key 同时清除）', () => this.deleteModelProfile(id));
        }
    },

    /**
     * 删除模型档案
     */
    async deleteModelProfile(id) {
        try {
            const r = await API.deleteModelProfile(id);
            if (r.success) {
                App.showNotification(r.message || '已删除', 'success');
                this.loadModelProfiles();
            } else {
                App.showNotification('删除失败: ' + (r.message || r.detail), 'error');
            }
        } catch (e) {
            App.showNotification('删除失败: ' + e.message, 'error');
        }
    },

    /**
     * 打开添加/编辑模型表单
     */
    openModelForm(profile) {
        document.getElementById('modelFormTitle').textContent = profile ? '编辑模型' : '添加模型';
        document.getElementById('mpEditId').value = profile ? profile.id : '';
        document.getElementById('mpName').value = profile ? profile.name : '';
        document.getElementById('mpId').value = profile ? profile.id : '';
        document.getElementById('mpBaseUrl').value = profile ? profile.base_url : '';
        document.getElementById('mpApiKey').value = '';
        document.getElementById('mpApiKey').placeholder = profile && profile.api_key_set ? '已配置（输入新值可更改）' : '输入API Key';
        document.getElementById('mpIsActive').checked = profile ? profile.is_active : false;

        // 提供商模板下拉
        const catalogSel = document.getElementById('mpCatalog');
        catalogSel.innerHTML = '<option value="__none__">-- 手动填写 --</option><option value="__custom__">自定义提供商</option>';
        Object.keys(this.catalog || {}).forEach(k => {
            const opt = document.createElement('option');
            opt.value = k;
            opt.textContent = (this.catalog[k].name || k) + ' (' + k + ')';
            catalogSel.appendChild(opt);
        });
        catalogSel.value = '__none__';
        if (profile && this.catalog && this.catalog[profile.id]) {
            catalogSel.value = profile.id;
        }
        this.updateIdGroup(catalogSel.value === '__custom__' || catalogSel.value === '__none__');

        // 模型列表 + 当前使用模型
        this.renderModelRows(profile ? (profile.models || []) : [], profile ? profile.active_model : '');
        document.getElementById('modelFormModal').classList.add('active');
    },

    /**
     * 档案 ID 是否可编辑（内置模板不可改）
     */
    updateIdGroup(editable) {
        document.getElementById('mpId').disabled = !editable;
        const hint = document.getElementById('mpCatalogHint');
        if (hint) hint.textContent = editable ? '' : '使用内置提供商 ID，不可修改';
    },

    /**
     * 提供商模板切换：预填名称/地址/模型
     */
    onCatalogChange() {
        const v = document.getElementById('mpCatalog').value;
        if (v === '__custom__' || v === '__none__') {
            this.updateIdGroup(true);
            if (v === '__custom__') {
                document.getElementById('mpName').value = '';
                document.getElementById('mpBaseUrl').value = '';
                document.getElementById('mpId').value = '';
                this.renderModelRows([], '');
            }
            return;
        }
        const info = (this.catalog || {})[v];
        if (!info) return;
        this.updateIdGroup(false);
        document.getElementById('mpName').value = info.name || v;
        document.getElementById('mpBaseUrl').value = info.base_url || '';
        document.getElementById('mpId').value = v;
        const models = (info.models || []).slice();
        this.renderModelRows(models, models[0] || '');
    },

    /**
     * 渲染模型输入行
     */
    renderModelRows(models, activeModel) {
        const list = document.getElementById('mpModelList');
        list.innerHTML = '';
        (models || []).forEach(m => this.addModelRow(m));
        this.refreshActiveModelOptions(activeModel);
    },

    /**
     * 添加一行模型输入
     */
    addModelRow(value) {
        const list = document.getElementById('mpModelList');
        const row = document.createElement('div');
        row.className = 'model-id-row';
        row.innerHTML = `
            <input type="text" class="mp-model-input" placeholder="模型 ID，如 deepseek-chat" value="${this.escapeHtml(value || '')}">
            <button class="btn-icon btn-remove-model" title="移除"><span>×</span></button>`;
        list.appendChild(row);
        this.refreshActiveModelOptions();
    },

    /**
     * 刷新「当前使用模型」下拉
     */
    refreshActiveModelOptions(activeModel) {
        const sel = document.getElementById('mpActiveModel');
        if (!sel) return;
        const models = Array.from(document.querySelectorAll('#mpModelList .mp-model-input'))
            .map(i => i.value.trim()).filter(Boolean);
        const current = activeModel || sel.value || models[0] || '';
        sel.innerHTML = '<option value="">-- 选择 --</option>';
        models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = m;
            if (m === current) opt.selected = true;
            sel.appendChild(opt);
        });
    },

    /**
     * 保存模型档案（新增或更新）
     */
    async saveModelProfile() {
        const editId = document.getElementById('mpEditId').value;
        const models = Array.from(document.querySelectorAll('#mpModelList .mp-model-input'))
            .map(i => i.value.trim()).filter(Boolean);
        const payload = {
            id: editId || document.getElementById('mpId').value.trim(),
            name: document.getElementById('mpName').value.trim(),
            base_url: document.getElementById('mpBaseUrl').value.trim(),
            api_key: document.getElementById('mpApiKey').value || undefined,
            models,
            active_model: document.getElementById('mpActiveModel').value || (models[0] || ''),
            is_active: document.getElementById('mpIsActive').checked,
        };

        if (!payload.name) { App.showNotification('请输入显示名称', 'warning'); return; }
        if (!payload.id) { App.showNotification('请输入档案 ID', 'warning'); return; }
        if (!payload.base_url) { App.showNotification('请输入 API Base URL', 'warning'); return; }
        if (!models.length) { App.showNotification('请至少添加一个模型', 'warning'); return; }

        try {
            const r = editId
                ? await API.updateModelProfile(editId, payload)
                : await API.createModelProfile(payload);
            if (r.success) {
                App.showNotification(r.message || '已保存', 'success');
                this.closeModelForm();
                this.loadModelProfiles();
            } else {
                App.showNotification('保存失败: ' + (r.message || r.detail), 'error');
            }
        } catch (e) {
            App.showNotification('保存失败: ' + e.message, 'error');
        }
    },

    /**
     * 关闭模型表单
     */
    closeModelForm() {
        const modal = document.getElementById('modelFormModal');
        if (modal) modal.classList.remove('active');
    },
};

// 导出Settings对象
window.Settings = Settings;