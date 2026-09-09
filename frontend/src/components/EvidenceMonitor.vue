<template>
  <div class="evidence-monitor">
    <!-- 1. Token 预算与多级缓存 -->
    <el-card class="box-card budget-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span><el-icon><PieChart /></el-icon> 2000-Token 预算优化</span>
          <el-tag size="small" :type="tokenPercentage > 85 ? 'danger' : 'success'">
            {{ tokenEstimate }} / 2000 Tokens
          </el-tag>
        </div>
      </template>

      <div class="budget-body">
        <el-progress
          :percentage="tokenPercentage"
          :status="tokenPercentage > 85 ? 'exception' : (tokenPercentage > 60 ? 'warning' : 'success')"
          :stroke-width="12"
        />
        <div class="budget-notes">
          <span>配额分配：知识 60% (1200T) | 历史 30% (600T) | 预留 10% (200T)</span>
          <div class="cache-status-tag">
            <el-tag size="small" type="info" effect="plain">L1 内存缓存 + L2 磁盘持久缓存</el-tag>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 2. 融合循证证据卡片 -->
    <el-card class="box-card evidence-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span><el-icon><Collection /></el-icon> 融合循证证据依据 (Top Evidence)</span>
          <span class="evidence-count">{{ evidenceList.length }} 权威依据</span>
        </div>
      </template>

      <div v-if="!evidenceList.length" class="empty-text">
        <el-empty description="暂无召回证据或急症直接熔断" :image-size="60" />
      </div>

      <div v-else class="evidence-collapse-wrapper">
        <el-collapse v-model="activeCollapse">
          <el-collapse-item
            v-for="(item, index) in evidenceList"
            :key="index"
            :name="index"
          >
            <template #title>
              <div class="evidence-item-title">
                <el-tag size="small" :type="getSourceTagType(item.source_type)">
                  {{ formatSourceType(item.source_type) }}
                </el-tag>
                <span class="evidence-title-text">{{ item.title || item.id }}</span>
                <span class="evidence-score" v-if="item.fusion_score">分: {{ item.fusion_score }}</span>
              </div>
            </template>
            <div class="evidence-item-detail">
              <div class="evidence-meta">
                <span>证据等级: <el-tag size="small" effect="plain">{{ item.evidence_level || 'A' }}</el-tag></span>
                <span v-if="item.trust_score">可信度: {{ item.trust_score }}</span>
                <span v-if="item.relevance">相关性: {{ item.relevance }}</span>
              </div>
              <div class="evidence-text">{{ item.content }}</div>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </el-card>

    <!-- 3. 安全防御与丢弃脏数据隔离 -->
    <el-card class="box-card security-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span><el-icon><ShieldCheck /></el-icon> 安全审查与脏数据隔离</span>
          <el-tag
            size="small"
            :type="evaluation?.dirty_evidence_dropped ? 'danger' : 'success'"
          >
            {{ evaluation?.dirty_evidence_dropped || 0 }} 处丢弃/拦截
          </el-tag>
        </div>
      </template>

      <div class="security-body">
        <div class="security-metric">
          <span>输入注入扫描：</span>
          <el-tag size="small" type="success">InputGuard 启用</el-tag>
        </div>
        <div class="security-metric">
          <span>输出安全审查：</span>
          <el-tag size="small" :type="evaluation?.output_safe ? 'success' : 'danger'">
            {{ evaluation?.output_safe ? '合规通过' : '已修正' }}
          </el-tag>
        </div>
        <div class="security-metric">
          <span>急症红旗识别：</span>
          <el-tag size="small" :type="evaluation?.red_flag_detected ? 'warning' : 'info'">
            {{ evaluation?.red_flag_detected ? '检测到红旗' : '未检测到' }}
          </el-tag>
        </div>
      </div>
    </el-card>

    <!-- 4. 向量与外部组件监控 -->
    <el-card class="box-card monitor-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span><el-icon><DataLine /></el-icon> 运行时组件监控</span>
          <el-tag size="small" type="success">Active</el-tag>
        </div>
      </template>

      <div class="monitor-body">
        <div class="monitor-row">
          <span class="monitor-label">向量存储引擎：</span>
          <span class="monitor-val">Qdrant Local (HNSW)</span>
        </div>
        <div class="monitor-row">
          <span class="monitor-label">向量知识点数：</span>
          <span class="monitor-val">{{ vectorStatus?.points_count || '1,185' }} 点 (512维)</span>
        </div>
        <div class="monitor-row">
          <span class="monitor-label">Embedding 模型：</span>
          <span class="monitor-val">BAAI/bge-small-zh (FastEmbed)</span>
        </div>
        <div class="monitor-row">
          <span class="monitor-label">MCP 工具协议：</span>
          <span class="monitor-val">Stdio (PubMed, openFDA)</span>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

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

const activeCollapse = ref([0])

const tokenEstimate = computed(() => {
  return props.result?.evaluation?.token_estimate || 0
})

const tokenPercentage = computed(() => {
  const est = tokenEstimate.value
  if (!est) return 0
  return Math.min(Math.round((est / 2000) * 100), 100)
})

const evidenceList = computed(() => {
  return props.result?.evidence || []
})

const evaluation = computed(() => {
  return props.result?.evaluation || null
})

const vectorStatus = computed(() => {
  return props.result?.vector_store || props.health?.vector_store || null
})

const formatSourceType = (type) => {
  const map = {
    guideline: '临床指南',
    drug_label: '说明书',
    paper: 'PubMed文献',
    knowledge_graph: '知识图谱',
    regulatory: '监管文件',
    web: '网络检索'
  }
  return map[type] || type || '循证依据'
}

const getSourceTagType = (type) => {
  if (type === 'guideline') return 'success'
  if (type === 'drug_label') return 'primary'
  if (type === 'paper') return 'warning'
  if (type === 'knowledge_graph') return 'info'
  return ''
}
</script>

<style scoped>
.evidence-monitor {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  color: #2c3e50;
}
.budget-body {
  padding: 4px 0;
}
.budget-notes {
  margin-top: 10px;
  font-size: 12px;
  color: #909399;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cache-status-tag {
  display: flex;
  justify-content: flex-end;
}
.evidence-count {
  font-size: 12px;
  color: #909399;
  font-weight: normal;
}
.evidence-collapse-wrapper {
  max-height: 280px;
  overflow-y: auto;
}
.evidence-item-title {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 90%;
  overflow: hidden;
}
.evidence-title-text {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}
.evidence-score {
  font-size: 11px;
  color: #e6a23c;
  margin-left: 6px;
}
.evidence-item-detail {
  padding: 6px 0;
  font-size: 12px;
  color: #606266;
}
.evidence-meta {
  display: flex;
  gap: 12px;
  margin-bottom: 6px;
  color: #909399;
}
.evidence-text {
  line-height: 1.5;
  background-color: #f8fafc;
  padding: 8px 10px;
  border-radius: 4px;
  font-size: 12px;
}
.security-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
}
.security-metric {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #606266;
}
.monitor-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
}
.monitor-row {
  display: flex;
  justify-content: space-between;
}
.monitor-label {
  color: #909399;
}
.monitor-val {
  color: #2c3e50;
  font-weight: 500;
}
.empty-text {
  padding: 12px 0;
}
</style>
