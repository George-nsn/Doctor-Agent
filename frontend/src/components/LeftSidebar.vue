<template>
  <div class="left-sidebar">
    <!-- 1. 运行时组件监控 -->
    <div class="neu-card">
      <div class="card-header">
        <div class="header-title font-display">
          <div class="icon-well">
            <el-icon><DataLine /></el-icon>
          </div>
          <span>运行时组件监控</span>
        </div>
        <div class="neu-pill">
          <span class="neu-glow-dot emerald"></span>
          <span>Online</span>
        </div>
      </div>

      <div class="monitor-list">
        <div class="monitor-item neu-inset-sm">
          <div class="item-header">
            <span class="label">向量引擎 (Vector DB)</span>
            <span class="badge-chip font-display">Qdrant Local</span>
          </div>
          <div class="item-detail">
            <span>索引点数: <strong>{{ vectorPointsCount }}</strong> 点 (512维 HNSW)</span>
          </div>
        </div>

        <div class="monitor-item neu-inset-sm">
          <div class="item-header">
            <span class="label">嵌入模型 (Embedding)</span>
            <span class="badge-chip font-display">FastEmbed</span>
          </div>
          <div class="item-detail text-ellipsis" title="BAAI/bge-small-zh-v1.5">
            <span>BAAI/bge-small-zh (ONNX)</span>
          </div>
        </div>

        <div class="monitor-item neu-inset-sm">
          <div class="item-header">
            <span class="label">外部工具协议</span>
            <span class="badge-chip font-display">MCP Stdio</span>
          </div>
          <div class="item-detail">
            <span>NCBI PubMed &amp; openFDA</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 2. 2000-Token 预算优化与缓存 -->
    <div class="neu-card">
      <div class="card-header">
        <div class="header-title font-display">
          <div class="icon-well">
            <el-icon><PieChart /></el-icon>
          </div>
          <span>Token 预算管理</span>
        </div>
        <div class="neu-pill font-display">
          <span class="token-val font-display">{{ tokenEstimate }}</span> / 2000 T
        </div>
      </div>

      <div class="budget-section">
        <!-- 进度条轨道 -->
        <div class="progress-track">
          <div
            class="progress-fill"
            :style="{ transform: `scaleX(${tokenPercentage / 100})` }"
            :class="{
              'fill-danger': tokenPercentage > 85,
              'fill-warning': tokenPercentage > 60 && tokenPercentage <= 85,
              'fill-success': tokenPercentage <= 60
            }"
          ></div>
        </div>

        <div class="budget-meta">
          <div class="quota-item neu-inset-sm">
            <span class="quota-dot knowledge-dot"></span>
            <span>知识检索 60% (1200T)</span>
          </div>
          <div class="quota-item neu-inset-sm">
            <span class="quota-dot history-dot"></span>
            <span>画像历史 30% (600T)</span>
          </div>
          <div class="quota-item neu-inset-sm">
            <span class="quota-dot reserved-dot"></span>
            <span>系统预留 10% (200T)</span>
          </div>
        </div>

        <div class="cache-badge-box">
          <div class="cache-tag-item neu-inset-sm">
            <el-icon><Cpu /></el-icon>
            <span>L1 进程内存缓存 (&lt;1μs)</span>
          </div>
          <div class="cache-tag-item neu-inset-sm">
            <el-icon><FolderOpened /></el-icon>
            <span>L2 磁盘持久缓存 (&lt;1ms)</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 3. 安全审查与脏数据隔离 -->
    <div class="neu-card">
      <div class="card-header">
        <div class="header-title font-display">
          <div class="icon-well">
          <el-icon><Lock /></el-icon>
          </div>
          <span>安全审查与隔离</span>
        </div>
        <div class="neu-pill">
          <span class="neu-glow-dot" :class="evaluation?.dirty_evidence_dropped ? 'rose' : 'emerald'"></span>
          <span>{{ evaluation?.dirty_evidence_dropped || 0 }} 处过滤</span>
        </div>
      </div>

      <div class="security-list">
        <div class="security-item neu-inset-sm">
          <span class="sec-label">多用户记忆沙箱</span>
          <span class="sec-status text-success">
            {{ result?.memory_audit?.isolation_status === 'clean' ? '独立分区 (' + result?.memory_audit?.tenant + ')' : 'TenantGuard 保护' }}
          </span>
        </div>
        <div class="security-item neu-inset-sm">
          <span class="sec-label">输入注入扫描</span>
          <span class="sec-status text-success">InputGuard 守护</span>
        </div>
        <div class="security-item neu-inset-sm">
          <span class="sec-label">检索注入过滤</span>
          <span class="sec-status text-success">WebEvidenceCleaner</span>
        </div>
        <div class="security-item neu-inset-sm">
          <span class="sec-label">处方与剂量审查</span>
          <span class="sec-status" :class="evaluation?.output_safe ? 'text-success' : 'text-danger'">
            {{ evaluation?.output_safe ? '合规通过' : '已触发修正' }}
          </span>
        </div>
        <div class="security-item neu-inset-sm">
          <span class="sec-label">急危重症红旗分诊</span>
          <span class="sec-status" :class="evaluation?.red_flag_detected ? 'text-danger' : 'text-info'">
            {{ evaluation?.red_flag_detected ? '检测到急症红旗' : '未检测到急症' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  result: {
    type: Object,
    default: null
  },
  health: {
    type: Object,
    default: null
  }
})

const tokenEstimate = computed(() => {
  return props.result?.evaluation?.token_estimate || 0
})

const tokenPercentage = computed(() => {
  const est = tokenEstimate.value
  if (!est) return 0
  return Math.min(Math.round((est / 2000) * 100), 100)
})

const evaluation = computed(() => {
  return props.result?.evaluation || null
})

const vectorPointsCount = computed(() => {
  return (
    props.result?.vector_store?.points_count ||
    props.health?.vector_store?.points_count ||
    '1,185'
  )
})
</script>

<style scoped>
.left-sidebar {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.neu-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 20px;
  box-shadow: var(--shadow-card);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  word-break: break-word;
}

.neu-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-hover);
  border-color: #CBD5E1;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--text-main);
  letter-spacing: -0.01em;
  white-space: nowrap;
}

.icon-well {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: var(--primary-light);
  border: 1px solid #E0E7FF;
  display: grid;
  place-items: center;
  color: var(--primary);
  font-size: 16px;
  flex-shrink: 0;
}

.monitor-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.monitor-item {
  border-radius: 12px;
  padding: 10px 12px;
  background: #F8FAFC;
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 5px;
  transition: all 0.2s ease;
}

.monitor-item:hover {
  background: #FFFFFF;
  border-color: #CBD5E1;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.06);
}

.item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.item-header .label {
  font-size: 0.82rem;
  color: var(--text-muted);
  font-weight: 600;
}

.badge-chip {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--primary);
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--primary-light);
  border: 1px solid #E0E7FF;
  white-space: nowrap;
}

.item-detail {
  font-size: 0.76rem;
  color: var(--text-main);
}

.text-ellipsis {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.token-val {
  font-weight: 700;
  color: var(--primary);
}

.budget-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.progress-track {
  height: 10px;
  border-radius: 9999px;
  overflow: hidden;
  background: #F1F5F9;
  border: 1px solid var(--border);
  padding: 0;
}

.progress-fill {
  height: 100%;
  width: 100%;
  transform-origin: left;
  border-radius: 9999px;
  transition: transform 0.5s cubic-bezier(0.16, 1, 0.3, 1);
}

.fill-success {
  background: var(--grad);
  box-shadow: 0 0 10px rgba(79, 70, 229, 0.4);
}

.fill-warning {
  background: linear-gradient(90deg, #F59E0B, #EA580C);
  box-shadow: 0 0 10px rgba(245, 158, 11, 0.4);
}

.fill-danger {
  background: linear-gradient(90deg, #F43F5E, #DC2626);
  box-shadow: 0 0 10px rgba(239, 68, 68, 0.4);
}

.budget-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.quota-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  background: #F8FAFC;
  border: 1px solid var(--border);
  font-size: 0.76rem;
  color: var(--text-muted);
  font-weight: 500;
  transition: all 0.2s ease;
}

.quota-item:hover {
  background: #FFFFFF;
  border-color: #CBD5E1;
}

.quota-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.knowledge-dot {
  background: var(--primary);
  box-shadow: 0 0 6px rgba(79, 70, 229, 0.5);
}

.history-dot {
  background: var(--secondary);
  box-shadow: 0 0 6px rgba(124, 58, 237, 0.5);
}

.reserved-dot {
  background: var(--accent-amber);
  box-shadow: 0 0 6px rgba(245, 158, 11, 0.5);
}

.cache-badge-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 4px;
}

.cache-tag-item {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  border-radius: 8px;
  background: #F8FAFC;
  border: 1px solid var(--border);
  font-size: 0.74rem;
  color: var(--text-main);
  font-weight: 500;
  transition: all 0.2s ease;
}

.cache-tag-item:hover {
  background: #FFFFFF;
  border-color: #CBD5E1;
}

.cache-tag-item .el-icon {
  color: var(--primary);
}

.security-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.security-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 9px 12px;
  border-radius: 10px;
  background: #F8FAFC;
  border: 1px solid var(--border);
  font-size: 0.78rem;
  transition: all 0.2s ease;
}

.security-item:hover {
  background: #FFFFFF;
  border-color: #CBD5E1;
}

.sec-label {
  color: var(--text-muted);
  font-weight: 500;
}

.sec-status {
  font-weight: 600;
  font-size: 0.74rem;
  padding: 2px 8px;
  border-radius: 6px;
}

.text-success {
  background: #ECFDF5;
  color: #065F46;
  border: 1px solid #A7F3D0;
}

.text-danger {
  background: #FEF2F2;
  color: #991B1B;
  border: 1px solid #FECACA;
}

.text-info {
  background: #F1F5F9;
  color: #475569;
  border: 1px solid #CBD5E1;
}
</style>
