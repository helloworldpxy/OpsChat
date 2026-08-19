/**
 * 工具卡片模块
 * 工具渲染注册表：工具名 -> 渲染器
 * ToolRow 单行摘要（状态点 + 图标 + 标题 + 截断摘要），点击展开 IN（参数）/ OUT（结果）
 */

const ToolCards = {
    // 工具名 -> 文字标记与人类可读标题
    TOOLS: {
        get_system_info:       { glyph: '系', title: '系统信息' },
        get_disk_usage:        { glyph: '盘', title: '磁盘使用率' },
        get_memory_usage:      { glyph: '存', title: '内存使用率' },
        get_cpu_usage:         { glyph: '处', title: 'CPU 使用率' },
        get_network_status:    { glyph: '网', title: '网络状态' },
        get_network_connections: { glyph: '连', title: '网络连接' },
        ping_host:             { glyph: '测', title: 'Ping 测试' },
        get_process_list:      { glyph: '程', title: '进程列表' },
        get_process_detail:    { glyph: '程', title: '进程详情' },
        kill_process:          { glyph: '杀', title: '终止进程' },
        list_services:         { glyph: '服', title: '服务列表' },
        get_service_status:    { glyph: '服', title: '服务状态' },
        start_service:         { glyph: '启', title: '启动服务' },
        stop_service:          { glyph: '停', title: '停止服务' },
        restart_service:       { glyph: '重', title: '重启服务' },
        get_system_logs:       { glyph: '志', title: '系统日志' },
        dmesg_kernel_log:      { glyph: '核', title: '内核日志' },
        read_file:             { glyph: '读', title: '读取文件' },
        write_file:            { glyph: '写', title: '写入文件' },
        delete_file:           { glyph: '删', title: '删除文件' },
        chmod:                 { glyph: '权', title: '修改权限' },
        config_drift_check:    { glyph: '检', title: '配置漂移检测' },
        diagnose_system:       { glyph: '诊', title: '系统诊断' },
        iostat_disk_io:        { glyph: 'IO', title: 'IO 统计' },
        lsof_ports:            { glyph: '占', title: '文件占用' },
        netstat_connections:   { glyph: '连', title: '端口连接' },
        detect_zombies:        { glyph: '僵', title: '僵尸进程检测' },
        // 兼容旧名别名（历史调用/自定义工具沿用）
        ping:                  { glyph: '测', title: 'Ping 测试' },
        check_config_drift:    { glyph: '检', title: '配置漂移检测' },
        get_dmesg:             { glyph: '核', title: '内核日志' },
        get_iostat:            { glyph: 'IO', title: 'IO 统计' },
        get_lsof:              { glyph: '占', title: '文件占用' },
        get_journal_logs:      { glyph: '志', title: '查看日志' },
    },

    // 自定义摘要渲染器：工具名 -> function(args) => 摘要文本
    renderers: {},

    STATUS: { pending: 'pending', running: 'running', success: 'success', error: 'error' },

    /**
     * 获取工具元信息（默认 fallback）
     */
    meta(toolName) {
        return this.TOOLS[toolName] || { glyph: '工', title: toolName };
    },

    /**
     * 生成人类可读的调用摘要
     */
    summarize(toolName, args = {}) {
        const custom = this.renderers[toolName];
        if (custom) {
            try {
                const text = custom(args);
                if (text) return text;
            } catch (e) { /* 忽略渲染器异常 */ }
        }

        // 默认：k=v 列表
        const entries = Object.entries(args || {})
            .filter(([, v]) => v !== '' && v !== undefined && v !== null);
        return entries.map(([k, v]) => {
            const val = typeof v === 'object' ? JSON.stringify(v) : String(v);
            return `${k}=${val}`;
        }).join(', ');
    },

    /**
     * 转义 HTML（参数/结果安全展示）
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    },

    /**
     * 创建工具卡片
     * @param {Object} opts { toolName, status, summary, inData, outData, callId }
     * @returns {HTMLElement}
     */
    createCard(opts) {
        const { toolName, status = this.STATUS.pending, summary = '', inData, outData, callId } = opts;
        const meta = this.meta(toolName);

        const card = document.createElement('div');
        card.className = `tool-card status-${status}`;
        card.dataset.tool = toolName;
        if (callId) card.dataset.callId = callId;

        const header = document.createElement('div');
        header.className = 'tool-card-header';

        const dot = document.createElement('span');
        dot.className = 'tool-status-dot';

        const glyph = document.createElement('span');
        glyph.className = 'tool-card-icon';
        glyph.textContent = meta.glyph;

        const title = document.createElement('span');
        title.className = 'tool-card-title';
        title.textContent = meta.title;

        const args = document.createElement('span');
        args.className = 'tool-card-args';
        args.textContent = summary || '';
        args.title = summary;

        const toggle = document.createElement('button');
        toggle.className = 'tool-card-toggle';
        toggle.type = 'button';
        toggle.textContent = '▾';

        header.append(dot, glyph, title, args, toggle);

        const body = document.createElement('div');
        body.className = 'tool-card-body hidden';
        if (inData !== undefined) {
            const inRow = document.createElement('div');
            inRow.className = 'tool-card-row';
            inRow.innerHTML = `<span class="tool-card-label">IN</span><pre><code>${this.escapeHtml(typeof inData === 'string' ? inData : JSON.stringify(inData, null, 2))}</code></pre>`;
            body.appendChild(inRow);
        }
        if (outData !== undefined) {
            const outRow = document.createElement('div');
            outRow.className = 'tool-card-row';
            outRow.innerHTML = `<span class="tool-card-label">OUT</span><pre><code>${this.escapeHtml(typeof outData === 'string' ? outData : JSON.stringify(outData, null, 2))}</code></pre>`;
            body.appendChild(outRow);
        }

        card.appendChild(header);
        card.appendChild(body);

        // 点击头部展开/收起
        header.addEventListener('click', (e) => {
            if (e.target.closest('.tool-card-toggle') || e.target.closest('button')) return;
            const isOpen = !body.classList.contains('hidden');
            body.classList.toggle('hidden', isOpen);
            toggle.classList.toggle('open', !isOpen);
            card.classList.toggle('expanded', !isOpen);
        });
        toggle.addEventListener('click', () => {
            const isOpen = !body.classList.contains('hidden');
            body.classList.toggle('hidden', isOpen);
            toggle.classList.toggle('open', !isOpen);
            card.classList.toggle('expanded', !isOpen);
        });

        return card;
    },

    /**
     * 渲染工具调用卡片（IN 侧）
     */
    renderToolCall(toolCall) {
        let args = {};
        try {
            args = JSON.parse(toolCall.function.arguments || '{}');
        } catch (e) { /* 参数非法时按空处理 */ }

        return this.createCard({
            toolName: toolCall.function.name,
            status: this.STATUS.pending,
            summary: this.summarize(toolCall.function.name, args),
            inData: args,
            callId: toolCall.id,
        });
    },

    /**
     * 渲染/更新工具结果（OUT 侧）
     * @param {string} toolName 工具名
     * @param {Object} result 执行结果
     * @param {string|null} callId 工具调用ID（用于关联已创建的卡片）
     * @param {Map} cardMap 本轮会话的卡片索引（callId -> element）
     */
    renderToolResult(toolName, result, callId, cardMap) {
        let card = callId && cardMap ? cardMap.get(callId) : null;

        // 提取摘要文本
        let summary = this._summarizeResult(toolName, result);

        if (!card) {
            // 没有前置卡片（如直接返回结果），新建一张
            card = this.createCard({
                toolName,
                summary,
                outData: result,
                callId,
            });
            return { card, created: true };
        }

        // 更新现有卡片：状态 + OUT + 摘要
        const ok = result && result.success !== false;
        card.classList.remove('status-pending', 'status-running', 'status-success', 'status-error');
        card.classList.add(ok ? 'status-success' : 'status-error');

        const argsEl = card.querySelector('.tool-card-args');
        if (argsEl && summary) {
            argsEl.textContent = summary;
            argsEl.title = summary;
        }

        const body = card.querySelector('.tool-card-body');
        const outRow = document.createElement('div');
        outRow.className = 'tool-card-row';
        outRow.innerHTML = `<span class="tool-card-label">OUT</span><pre><code>${this.escapeHtml(JSON.stringify(result, null, 2))}</code></pre>`;
        body.appendChild(outRow);

        return { card, created: false };
    },

    /**
     * 更新卡片运行状态（如执行中扫光）
     */
    setStatus(card, status) {
        if (!card) return;
        card.classList.remove('status-pending', 'status-running', 'status-success', 'status-error');
        card.classList.add(`status-${status}`);
    },

    /**
     * 从工具结果提取摘要
     */
    _summarizeResult(toolName, result) {
        try {
            const d = result?.result?.data || result?.data || result;
            if (d?.hostname) return d.hostname + ' | ' + (d.os || '');
            if (Array.isArray(d) && d[0]?.mountpoint) return d.map(p => p.mountpoint + ': ' + p.percent + '%').join(', ');
            if (d?.virtual_memory) return '内存: ' + d.virtual_memory.used_gb + '/' + d.virtual_memory.total_gb + 'GB (' + d.virtual_memory.percent + '%)';
            if (d?.logical_cores !== undefined) return 'CPU: ' + d.logical_cores + '核 | ' + (d.average_usage || 0).toFixed(1) + '%';
            if (d?.io_counters) return '网络IO: ' + (d.io_counters.bytes_recv / 1048576).toFixed(1) + 'MB';
            if (result?.success !== undefined) return result.success ? '执行成功' : (result.error || '执行完成');
            if (Array.isArray(d) && d.length > 0) return `${toolName} 返回 ${d.length} 项`;
            return '执行完成';
        } catch (e) {
            return '执行完成';
        }
    },
};

window.ToolCards = ToolCards;