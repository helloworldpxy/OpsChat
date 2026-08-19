/**
 * API调用封装模块
 * 处理与后端的所有通信
 */

const API = {
    baseUrl: '',
    
    /**
     * 发送请求
     */
    async request(url, options = {}) {
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
            },
        };
        
        const response = await fetch(this.baseUrl + url, {
            ...defaultOptions,
            ...options,
        });
        
        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: response.statusText }));
            let detail = err.detail || '请求失败';
            // pydantic 校验错误 detail 是数组，取第一条可读信息
            if (Array.isArray(detail)) {
                detail = detail.find(i => i && i.msg)?.msg || '请求参数错误';
            }
            throw new Error(detail);
        }
        
        return response.json();
    },
    
    /**
     * GET请求
     */
    async get(url) {
        return this.request(url, { method: 'GET' });
    },
    
    /**
     * POST请求
     */
    async post(url, data) {
        return this.request(url, {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },
    
    /**
     * DELETE请求
     */
    async delete(url) {
        return this.request(url, { method: 'DELETE' });
    },
    
    /**
     * PUT请求
     */
    async put(url, data) {
        return this.request(url, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    },
    
    // ==================== 对话API ====================
    
    /**
     * 发送消息
     */
    async sendMessage(message, sessionId = 'default', stream = false) {
        return this.post('/api/chat/', {
            message,
            session_id: sessionId,
            stream,
        });
    },
    
    /**
     * 流式发送消息
     * options.signal: 外部 AbortController 信号（切换/清空会话时用于中止流）
     * options.idleTimeoutMs: 空闲超时（毫秒），超时视为异常并中止
     */
    async sendMessageStream(message, sessionId = 'default', onChunk, onDone, onError, options = {}) {
        const controller = new AbortController();
        const externalSignal = options.signal || null;
        const idleTimeoutMs = options.idleTimeoutMs || 120000;
        let idleTimer = null;
        let idleTimedOut = false;
        let receivedDone = false;

        // 外部信号链到内部 controller，保证外部 abort 与空闲超时都能中断 fetch
        if (externalSignal) {
            if (externalSignal.aborted) controller.abort();
            else externalSignal.addEventListener('abort', () => controller.abort());
        }

        const resetIdle = () => {
            if (idleTimer) clearTimeout(idleTimer);
            idleTimer = setTimeout(() => {
                idleTimedOut = true;
                controller.abort();
            }, idleTimeoutMs);
        };

        try {
            const response = await fetch(this.baseUrl + '/api/chat/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message,
                    session_id: sessionId,
                    stream: true,
                }),
                signal: controller.signal,
            });

            if (!response.ok) {
                const err = await response.json().catch(() => ({ detail: response.statusText }));
                let detail = err.detail || '请求失败';
                if (Array.isArray(detail)) {
                    detail = detail.find(i => i && i.msg)?.msg || '请求参数错误';
                }
                throw new Error(detail);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            resetIdle();

            while (true) {
                const { done, value } = await reader.read();
                if (idleTimer) clearTimeout(idleTimer);

                if (done) {
                    break;
                }

                resetIdle();
                buffer += decoder.decode(value, { stream: true });

                // 处理SSE数据
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6);

                        if (data === '[DONE]') {
                            receivedDone = true;
                            onDone?.();
                            return;
                        }

                        try {
                            const chunk = JSON.parse(data);
                            onChunk?.(chunk);
                        } catch (e) {
                            console.warn('解析SSE数据失败:', e);
                        }
                    }
                }
            }

            // 流异常关闭（未收到 [DONE]）视为失败，避免半截回答被当成功
            if (!receivedDone) {
                throw new Error('连接中断：未收到完整的响应');
            }

            onDone?.();

        } catch (error) {
            if (error.name === 'AbortError') {
                if (idleTimedOut) {
                    onError?.(new Error('流式响应空闲超时，请检查网络或重试'));
                }
                return; // 外部主动中止，静默处理
            }
            onError?.(error);
        } finally {
            if (idleTimer) clearTimeout(idleTimer);
        }
    },
    
    /**
     * 确认工具执行（权限审批）
     */
    async confirmToolExecution(data) {
        return this.post('/api/chat/confirm', data);
    },

    /**
     * 权限审批确认（流式）：once/always/reject + sudo 密码
     */
    async confirmPermissionStream({ sessionId, requestId, reply, password }, onChunk, onDone, onError, options = {}) {
        const controller = new AbortController();
        const externalSignal = options.signal || null;
        const idleTimeoutMs = options.idleTimeoutMs || 120000;
        let idleTimer = null;
        let idleTimedOut = false;
        let receivedDone = false;

        // 外部信号链到内部 controller，保证外部 abort 与空闲超时都能中断 fetch
        if (externalSignal) {
            if (externalSignal.aborted) controller.abort();
            else externalSignal.addEventListener('abort', () => controller.abort());
        }

        const resetIdle = () => {
            if (idleTimer) clearTimeout(idleTimer);
            idleTimer = setTimeout(() => {
                idleTimedOut = true;
                controller.abort();
            }, idleTimeoutMs);
        };

        try {
            const response = await fetch(this.baseUrl + '/api/chat/confirm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessionId,
                    request_id: requestId,
                    reply,
                    password: password || '',
                    stream: true,
                }),
                signal: controller.signal,
            });

            if (!response.ok) {
                const err = await response.json().catch(() => ({ detail: response.statusText }));
                let detail = err.detail || '请求失败';
                if (Array.isArray(detail)) {
                    detail = detail.find(i => i && i.msg)?.msg || '请求参数错误';
                }
                throw new Error(detail);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            resetIdle();

            while (true) {
                const { done, value } = await reader.read();
                if (idleTimer) clearTimeout(idleTimer);
                if (done) break;
                resetIdle();
                buffer += decoder.decode(value, { stream: true });

                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6);
                        if (data === '[DONE]') {
                            receivedDone = true;
                            onDone?.();
                            return;
                        }
                        try {
                            onChunk?.(JSON.parse(data));
                        } catch (e) {
                            console.warn('解析审批流式数据失败:', e);
                        }
                    }
                }
            }

            if (!receivedDone) {
                throw new Error('连接中断：未收到完整的响应');
            }
            onDone?.();
        } catch (error) {
            if (error.name === 'AbortError') {
                if (idleTimedOut) {
                    onError?.(new Error('审批流式响应空闲超时，请检查网络或重试'));
                }
                return; // 外部主动中止，静默处理
            }
            onError?.(error);
        } finally {
            if (idleTimer) clearTimeout(idleTimer);
        }
    },
    
    /**
     * 清除对话历史
     */
    async clearConversation(sessionId) {
        return this.delete(`/api/chat/conversation/${sessionId}`);
    },

    // ==================== 检索API ====================

    /**
     * 全文检索
     */
    async search(q, scope = 'messages', limit = 50) {
        const params = new URLSearchParams({ q, scope, limit: String(limit) });
        return this.get(`/api/search?${params}`);
    },
    
    /**
     * 获取思维链追踪
     */
    async getTrace(traceId) {
        return this.get(`/api/chat/trace/${traceId}`);
    },
    
    // ==================== 工具API ====================
    
    /**
     * 获取所有工具
     */
    async getTools() {
        return this.get('/api/tools/');
    },
    
    /**
     * 获取LLM工具列表
     */
    async getLLMTools() {
        return this.get('/api/tools/llm');
    },
    
    /**
     * 获取工具详情
     */
    async getTool(toolName) {
        return this.get(`/api/tools/${toolName}`);
    },
    
    // ==================== 审计API ====================
    
    /**
     * 获取审计日志
     */
    async getAuditLogs(params = {}) {
        const queryString = new URLSearchParams(params).toString();
        return this.get(`/api/audit/logs?${queryString}`);
    },
    
    /**
     * 获取追踪列表
     */
    async getTraces() {
        return this.get('/api/audit/traces');
    },
    
    /**
     * 获取追踪详情
     */
    async getTraceDetail(traceId) {
        return this.get(`/api/audit/trace/${traceId}`);
    },
    
    /**
     * 清除追踪
     */
    async clearTraces() {
        return this.delete('/api/audit/traces');
    },

    /**
     * 导出审计日志（文件下载）
     */
    async exportAuditLogs(format = 'csv', params = {}) {
        const queryString = new URLSearchParams(params).toString();
        const response = await fetch(`${this.baseUrl}/api/audit/export?format=${format}&${queryString}`, {
            headers: { 'Content-Type': 'application/json' },
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || '导出失败');
        }
        const blob = await response.blob();
        let count = null;
        if (format === 'json') {
            try {
                const parsed = JSON.parse(await blob.text());
                count = parsed && typeof parsed.count === 'number' ? parsed.count : null;
            } catch (_) { /* 非标准 JSON 响应，忽略 */ }
        }
        const disposition = response.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="?([^";]+)"?/);
        const filename = match ? match[1] : `audit_export.${format}`;
        if (count === 0) {
            return { count: 0 };
        }
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        return { count };
    },
    
    // ==================== 设置API ====================
    
    /**
     * 获取设置
     */
    async getSettings() {
        return this.get('/api/settings/');
    },
    
    /**
     * 保存API配置
     */
    async saveApiConfig(config) {
        return this.post('/api/settings/api', config);
    },
    
    /**
     * 保存API配置到.env文件
     */
    async saveToEnv(config) {
        return this.post('/api/settings/save-to-env', config);
    },
    
    /**
     * 保存系统配置
     */
    async saveSystemConfig(config) {
        return this.post('/api/settings/system', config);
    },
    
    /**
     * 测试API连接
     */
    async testConnection() {
        return this.post('/api/settings/test-connection');
    },
    
    // ==================== 模型API ====================
    
    /**
     * 获取所有模型
     */
    async getModels() {
        return this.get('/api/models/');
    },
    
    /**
     * 获取提供商模型
     */
    async getProviderModels(provider) {
        return this.get(`/api/models/${provider}`);
    },

    // ==================== 模型档案API（多模型管理） ====================

    /**
     * 获取模型档案列表 + 内置提供商目录
     */
    async listModelProfiles() {
        return this.get('/api/settings/models');
    },

    /**
     * 新增模型档案
     */
    async createModelProfile(data) {
        return this.post('/api/settings/models', data);
    },

    /**
     * 更新模型档案
     */
    async updateModelProfile(id, data) {
        return this.put(`/api/settings/models/${encodeURIComponent(id)}`, data);
    },

    /**
     * 删除模型档案
     */
    async deleteModelProfile(id) {
        return this.delete(`/api/settings/models/${encodeURIComponent(id)}`);
    },

    /**
     * 激活模型档案
     */
    async activateModelProfile(id) {
        return this.post(`/api/settings/models/${encodeURIComponent(id)}/activate`);
    },

    /**
     * 测试模型档案连接
     */
    async testModelProfile(id) {
        return this.post(`/api/settings/models/${encodeURIComponent(id)}/test`);
    },
    
    // ==================== 系统API ====================
    
    /**
     * 获取系统状态
     */
    async getStatus() {
        return this.get('/api/status');
    },
};

// 导出API对象
window.API = API;
