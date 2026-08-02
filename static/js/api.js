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
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || '请求失败');
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
     */
    async sendMessageStream(message, sessionId = 'default', onChunk, onDone, onError) {
        try {
            const response = await fetch(this.baseUrl + '/api/chat/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message,
                    session_id: sessionId,
                    stream: true,
                }),
            });
            
            if (!response.ok) {
                const err = await response.json().catch(() => ({ detail: response.statusText }));
                throw new Error(err.detail || '请求失败');
            }
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            
            while (true) {
                const { done, value } = await reader.read();
                
                if (done) {
                    break;
                }
                
                buffer += decoder.decode(value, { stream: true });
                
                // 处理SSE数据
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6);
                        
                        if (data === '[DONE]') {
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
            
            onDone?.();
            
        } catch (error) {
            onError?.(error);
        }
    },
    
    /**
     * 确认工具执行
     */
    async confirmToolExecution(data) {
        return this.post('/api/chat/confirm', data);
    },
    
    /**
     * 清除对话历史
     */
    async clearConversation(sessionId) {
        return this.delete(`/api/chat/conversation/${sessionId}`);
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
