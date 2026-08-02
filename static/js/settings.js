/**
 * 设置功能模块
 * 处理API配置和系统设置
 */

const Settings = {
    currentProvider: 'deepseek',
    providers: {},
    
    /**
     * 初始化设置模块
     */
    init() {
        this.bindEvents();
        this.loadSettings();
        this.loadModels();
    },
    
    /**
     * 绑定事件
     */
    bindEvents() {
        // 提供商选择
        const providerSelect = document.getElementById('apiProvider');
        if (providerSelect) {
            providerSelect.addEventListener('change', () => {
                this.onProviderChange(providerSelect.value);
            });
        }
        
        // 显示/隐藏密码
        const toggleApiKey = document.getElementById('toggleApiKey');
        if (toggleApiKey) {
            toggleApiKey.addEventListener('click', () => {
                const input = document.getElementById('apiKey');
                const icon = toggleApiKey.querySelector('i');
                
                if (input.type === 'password') {
                    input.type = 'text';
                    icon.className = 'fas fa-eye-slash';
                } else {
                    input.type = 'password';
                    icon.className = 'fas fa-eye';
                }
            });
        }
        
        // 保存API配置
        const saveApiBtn = document.getElementById('saveApiBtn');
        if (saveApiBtn) {
            saveApiBtn.addEventListener('click', () => this.saveApiConfig());
        }
        
        // 保存到.env
        const saveToEnvBtn = document.getElementById('saveToEnvBtn');
        if (saveToEnvBtn) {
            saveToEnvBtn.addEventListener('click', () => this.saveToEnv());
        }
        
        // 测试连接
        const testConnectionBtn = document.getElementById('testConnectionBtn');
        if (testConnectionBtn) {
            testConnectionBtn.addEventListener('click', () => this.testConnection());
        }
        
        // 安全设置开关
        const securityToggles = ['enableGuardrail', 'enableInputSanitizer', 'enableOutputValidator', 'enableSandbox'];
        securityToggles.forEach(id => {
            const toggle = document.getElementById(id);
            if (toggle) {
                toggle.addEventListener('change', () => this.saveSystemConfig());
            }
        });
    },
    
    /**
     * 加载设置
     */
    async loadSettings() {
        try {
            const result = await API.getSettings();
            
            if (result.success) {
                const { api, security, providers } = result.data;
                
                // 保存提供商信息
                this.providers = providers;
                
                // 设置API配置
                document.getElementById('apiProvider').value = api.provider || 'deepseek';
                document.getElementById('apiBaseUrl').value = api.base_url || '';
                
                if (api.api_key_set) {
                    document.getElementById('apiKey').placeholder = '已设置 (输入新值可更改)';
                }
                
                // 加载模型列表
                this.onProviderChange(api.provider || 'deepseek');
                
                // 设置模型
                setTimeout(() => {
                    document.getElementById('apiModel').value = api.model || '';
                }, 100);
                
                // 设置安全配置
                document.getElementById('enableGuardrail').checked = security.enable_security_guardrail;
                document.getElementById('enableInputSanitizer').checked = security.enable_input_sanitizer;
                document.getElementById('enableOutputValidator').checked = security.enable_output_validator;
                document.getElementById('enableSandbox').checked = security.enable_sandbox;
            }
            
        } catch (error) {
            console.error('加载设置失败:', error);
        }
    },
    
    /**
     * 加载模型列表
     */
    async loadModels() {
        try {
            const result = await API.getModels();
            
            if (result.success) {
                this.providers = result.data;
            }
            
        } catch (error) {
            console.error('加载模型列表失败:', error);
        }
    },
    
    /**
     * 提供商变更处理
     */
    onProviderChange(provider) {
        this.currentProvider = provider;
        
        const providerInfo = this.providers[provider];
        if (!providerInfo) {
            return;
        }
        
        // 更新Base URL
        const baseUrlInput = document.getElementById('apiBaseUrl');
        if (provider !== 'custom') {
            baseUrlInput.value = providerInfo.base_url || '';
        } else {
            baseUrlInput.value = '';
            baseUrlInput.placeholder = '请输入API Base URL';
        }
        
        // 更新提供商描述提示
        const hintEl = document.getElementById('providerHint');
        if (hintEl) {
            if (providerInfo.description) {
                hintEl.textContent = providerInfo.description;
                hintEl.classList.add('visible');
            } else {
                hintEl.classList.remove('visible');
            }
        }
        
        // 更新模型列表
        const modelSelect = document.getElementById('apiModel');
        const modelCustom = document.getElementById('apiModelCustom');
        modelSelect.innerHTML = '<option value="">请选择模型</option>';
        
        if (providerInfo.models && providerInfo.models.length > 0) {
            providerInfo.models.forEach(model => {
                const option = document.createElement('option');
                option.value = model;
                option.textContent = model;
                modelSelect.appendChild(option);
            });
            // 添加"自定义"选项
            const customOption = document.createElement('option');
            customOption.value = '__custom__';
            customOption.textContent = '-- 手动输入模型名称 --';
            modelSelect.appendChild(customOption);
            modelSelect.style.display = '';
            modelCustom.style.display = 'none';
        } else {
            // 自定义提供商，显示输入框
            modelSelect.style.display = 'none';
            modelCustom.style.display = '';
        }
        
        // 监听模型选择变化
        modelSelect.onchange = () => {
            if (modelSelect.value === '__custom__') {
                modelCustom.style.display = '';
                modelCustom.focus();
            } else {
                modelCustom.style.display = 'none';
            }
        };
    },
    
    /**
     * 保存API配置
     */
    async saveApiConfig() {
        const provider = document.getElementById('apiProvider').value;
        const apiKey = document.getElementById('apiKey').value;
        const baseUrl = document.getElementById('apiBaseUrl').value;
        const modelSelect = document.getElementById('apiModel');
        const modelCustom = document.getElementById('apiModelCustom');
        
        // 获取模型名称（支持自定义输入）
        let model = modelSelect.value;
        if (model === '__custom__' || modelSelect.style.display === 'none') {
            model = modelCustom.value.trim();
        }
        
        if (!baseUrl) {
            App.showNotification('请输入API Base URL', 'warning');
            return;
        }
        
        if (!model) {
            App.showNotification('请选择或输入模型名称', 'warning');
            return;
        }
        
        if (!apiKey && !document.getElementById('apiKey').placeholder.includes('已设置')) {
            App.showNotification('请输入API Key', 'warning');
            return;
        }
        
        try {
            const result = await API.saveApiConfig({
                provider,
                api_key: apiKey || undefined,
                base_url: baseUrl,
                model,
            });
            
            if (result.success) {
                App.showNotification('API配置已保存', 'success');
            } else {
                App.showNotification('保存失败: ' + result.message, 'error');
            }
            
        } catch (error) {
            console.error('保存API配置失败:', error);
            App.showNotification('保存API配置失败', 'error');
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
    
    /**
     * 保存配置到.env文件
     */
    async saveToEnv() {
        const provider = document.getElementById('apiProvider').value;
        const apiKey = document.getElementById('apiKey').value;
        const baseUrl = document.getElementById('apiBaseUrl').value;
        const modelSelect = document.getElementById('apiModel');
        const modelCustom = document.getElementById('apiModelCustom');
        
        let model = modelSelect.value;
        if (model === '__custom__' || modelSelect.style.display === 'none') {
            model = modelCustom.value.trim();
        }
        
        if (!apiKey) {
            App.showNotification('请输入API Key后再保存', 'warning');
            return;
        }
        
        try {
            const result = await API.saveToEnv({
                provider,
                api_key: apiKey,
                base_url: baseUrl,
                model,
            });
            
            if (result.success) {
                App.showNotification('配置已保存到.env文件，重启后仍然生效', 'success');
                // 更新placeholder显示已保存
                document.getElementById('apiKey').placeholder = '已保存 (输入新值可更改)';
            } else {
                App.showNotification('保存失败: ' + result.message, 'error');
            }
        } catch (error) {
            console.error('保存到.env失败:', error);
            App.showNotification('保存到.env失败', 'error');
        }
    },
    
    /**
     * 测试连接
     */
    async testConnection() {
        const testBtn = document.getElementById('testConnectionBtn');
        const originalText = testBtn.innerHTML;
        
        testBtn.disabled = true;
        testBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> <span>测试中...</span>';
        
        try {
            const provider = document.getElementById('apiProvider').value;
            const apiKey = document.getElementById('apiKey').value;
            const baseUrl = document.getElementById('apiBaseUrl').value;
            const modelSelect = document.getElementById('apiModel');
            const modelCustom = document.getElementById('apiModelCustom');
            
            let model = modelSelect.value;
            if (model === '__custom__' || modelSelect.style.display === 'none') {
                model = modelCustom.value.trim();
            }
            
            // 发送当前表单数据进行测试
            const result = await API.post('/api/settings/test-connection', {
                provider,
                api_key: apiKey || undefined,
                base_url: baseUrl,
                model,
            });
            
            if (result.success) {
                App.showNotification('API连接成功', 'success');
            } else {
                App.showNotification('API连接失败: ' + result.message, 'error');
            }
            
        } catch (error) {
            console.error('测试连接失败:', error);
            App.showNotification('测试连接失败', 'error');
        } finally {
            testBtn.disabled = false;
            testBtn.innerHTML = originalText;
        }
    },
};

// 导出Settings对象
window.Settings = Settings;
