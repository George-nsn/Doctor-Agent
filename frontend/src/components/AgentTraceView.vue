<template>
  <div class="agent-trace-view">
    <!-- 1. 风险分级预警 Banner -->
    <div class="neu-card">
      <div v-if="!result" class="empty-state">
        <div class="empty-icon-well neu-inset-deep">
          <el-icon><Monitor /></el-icon>
        </div>
        <p class="empty-text">提交问诊后将在此展示多 Agent 推理分诊与循证链路</p>
      </div>

      <div v-else class="risk-active-box">
        <!-- Emergency -->
        <div v-if="riskLevel === 'emergency'" class="risk-banner banner-danger neu-inset-sm">
          <div class="banner-top">
            <span class="neu-glow-dot rose"></span>
            <strong>🚨 危急重症红旗警报 (Emergency) — 已触发短路熔断</strong>
          </div>
          <p class="banner-desc">
            识别到高危红旗体征（{{ redFlags.join('、') || '严重危险症状' }}）。
            <strong>请立即前往最近医院急诊科就诊或拨打 120！</strong>
            系统已自动阻断普通问答检索，优先提供急救指引。
          </p>
        </div>

        <!-- Medium -->
        <div v-else-if="riskLevel === 'medium'" class="risk-banner banner-warning neu-inset-sm">
          <div class="banner-top">
            <span class="neu-glow-dot amber"></span>
            <strong>⚠️ 中度临床风险评估 (Medium Risk) — 需线下就医确诊</strong>
          </div>
          <p class="banner-desc">
            存在持续加重疼痛或服药未缓解体征。建议及时前往医院专科面诊评估。
          </p>
        </div>

        <!-- Low -->
        <div v-else-if="riskLevel === 'low'" class="risk-banner banner-success neu-inset-sm">
          <div class="banner-top">
            <span class="neu-glow-dot emerald"></span>
            <strong>✅ 常规低风险咨询 (Low Risk)</strong>
          </div>
          <p class="banner-desc">
            未检测到急危重症红旗症状，建议对症观察并参照权威临床指南建议。
          </p>
        </div>

        <!-- 专科专家路由 -->
        <div class="experts-section">
          <div class="section-label font-display">
            <el-icon><Coordinate /></el-icon>
            <span>动态路由专科专家：</span>
          </div>
          <div class="experts-tags">
            <span
              v-for="expert in selectedExperts"
              :key="expert"
              class="expert-chip neu-pill font-display"
              :class="getExpertChipClass(expert)"
            >
              <span class="neu-glow-dot" :class="getExpertDotColor(expert)"></span>
              {{ formatExpertName(expert) }}
            </span>
          </div>
        </div>

        <!-- 驱动模型徽章 -->
        <div v-if="llmInfo && llmInfo.used" class="llm-badge-line">
          <div class="neu-pill font-display">
            <el-icon><Cpu /></el-icon>
            <span>驱动模型: <strong>{{ llmInfo.provider }}</strong> / {{ llmInfo.model }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 2. 融合循证证据依据 (Top Evidence) -->
    <div v-if="result" class="neu-card">
      <div class="card-header">
        <div class="header-title font-display">
          <div class="icon-well">
            <el-icon><Collection /></el-icon>
          </div>
          <span>融合循证证据依据</span>
        </div>
        <div class="neu-pill font-display">
          <span>{{ evidenceList.length }} 权威依据</span>
        </div>
      </div>

      <div v-if="!evidenceList.length" class="empty-evidence neu-inset-sm">
        <span>暂无召回证据或急症直接触发熔断</span>
      </div>

      <div v-else class="evidence-list">
        <div
          v-for="(item, index) in evidenceList"
          :key="index"
          class="evidence-card neu-inset-sm"
        >
          <div class="evidence-header" @click="toggleEvidence(index)">
            <div class="evidence-left">
              <span class="source-tag font-display" :class="getSourceClass(item.source_type)">
                {{ formatSourceType(item.source_type) }}
              </span>
              <span class="evidence-title" :title="item.title || item.id">
                {{ item.title || item.id }}
              </span>
            </div>
            <div class="evidence-right font-display">
              <span class="score-badge" v-if="item.fusion_score">得分: {{ item.fusion_score }}</span>
              <el-icon class="expand-icon" :class="{ 'is-expanded': expandedIndexes.includes(index) }">
                <ArrowDown />
              </el-icon>
            </div>
          </div>

          <el-collapse-transition>
            <div v-show="expandedIndexes.includes(index)" class="evidence-detail">
              <div class="evidence-badges">
                <span class="neu-pill font-display">等级: {{ item.evidence_level || 'A' }}</span>
                <span class="neu-pill font-display" v-if="item.trust_score">可信度: {{ item.trust_score }}</span>
                <span class="neu-pill font-display" v-if="item.relevance">相关性: {{ item.relevance }}</span>
              </div>
              <div class="evidence-content-text">
                {{ item.content }}
              </div>
            </div>
          </el-collapse-transition>
        </div>
      </div>
    </div>

    <!-- 3. LangGraph 状态图执行链路 Trace -->
    <div v-if="result && result.trace && result.trace.length" class="neu-card">
      <div class="card-header">
        <div class="header-title font-display">
          <div class="icon-well">
            <el-icon><Connection /></el-icon>
          </div>
          <span>LangGraph 状态图执行链路</span>
        </div>
        <div class="neu-pill font-display">
          <span>{{ result.trace.length }} 节点流转</span>
        </div>
      </div>

      <div class="trace-stepper">
        <div
          v-for="(item, index) in result.trace"
          :key="index"
          class="trace-step-item"
        >
          <div class="step-indicator">
            <div class="step-circle neu-inset-sm font-display" :class="getTraceCircleClass(item)">
              {{ index + 1 }}
            </div>
            <div v-if="index !== result.trace.length - 1" class="step-line"></div>
          </div>
          <div class="step-body neu-inset-sm">
            <div class="step-name font-display">{{ getTraceNode(item) }}</div>
            <div class="step-detail">{{ getTraceDetail(item) }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  result: {
    type: Object,
    default: null
  }
})

const expandedIndexes = ref([0])

const toggleEvidence = (index) => {
  if (expandedIndexes.value.includes(index)) {
    expandedIndexes.value = expandedIndexes.value.filter(i => i !== index)
  } else {
    expandedIndexes.value.push(index)
  }
}

const riskLevel = computed(() => {
  return props.result?.risk_assessment?.risk_level || 'unknown'
})

const redFlags = computed(() => {
  return props.result?.risk_assessment?.red_flags || []
})

const selectedExperts = computed(() => {
  return props.result?.selected_experts || []
})

const llmInfo = computed(() => {
  return props.result?.llm_generation || null
})

const evidenceList = computed(() => {
  return props.result?.evidence || []
})

const formatExpertName = (name) => {
  const map = {
    GeneralPracticeAgent: '全科医疗专家 (GP)',
    GastroenterologyAgent: '消化专科专家 (GI)',
    PharmacistAgent: '临床药师 (Pharmacist)',
    EmergencyResponseAgent: '急危重症专家 (Emergency)'
  }
  return map[name] || name
}

const getExpertDotColor = (name) => {
  if (name.includes('Emergency')) return 'rose'
  if (name.includes('Pharmacist')) return 'amber'
  if (name.includes('Gastroenterology')) return 'purple'
  return 'teal'
}

const getExpertChipClass = (name) => {
  if (name.includes('Emergency')) return 'chip-rose'
  return ''
}

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

const getSourceClass = (type) => {
  if (type === 'guideline') return 'src-guideline'
  if (type === 'drug_label') return 'src-drug'
  if (type === 'paper') return 'src-paper'
  return 'src-default'
}

const getTraceNode = (traceStr) => {
  const parts = traceStr.split(': ')
  return parts[0] || traceStr
}

const getTraceDetail = (traceStr) => {
  const parts = traceStr.split(': ')
  return parts.slice(1).join(': ') || ''
}

const getTraceCircleClass = (traceStr) => {
  if (traceStr.includes('Emergency') || traceStr.includes('risk=emergency')) return 'circle-danger'
  if (traceStr.includes('InputGuard') || traceStr.includes('OutputSafetyGuard')) return 'circle-warning'
  if (traceStr.includes('EvaluationHarness')) return 'circle-success'
  return 'circle-primary'
}
</script>

<style scoped>
.agent-trace-view {
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

.empty-state {
  padding: 32px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  text-align: center;
}

.empty-icon-well {
  width: 60px;
  height: 60px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  font-size: 26px;
  color: var(--text-light);
  background: #F8FAFC;
  border: 1px solid var(--border);
}

.empty-text {
  font-size: 0.82rem;
  color: var(--text-muted);
  line-height: 1.5;
}

.risk-active-box {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.risk-banner {
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.banner-danger {
  background: #FEF2F2;
  border: 1px solid #FECACA;
}

.banner-warning {
  background: #FFFBEB;
  border: 1px solid #FDE68A;
}

.banner-success {
  background: #F0FDF4;
  border: 1px solid #A7F3D0;
}

.banner-top {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.84rem;
}

.banner-danger .banner-top {
  color: #991B1B;
}

.banner-warning .banner-top {
  color: #92400E;
}

.banner-success .banner-top {
  color: #065F46;
}

.banner-desc {
  font-size: 0.77rem;
  color: var(--text-main);
  line-height: 1.55;
}

.experts-section {
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.78rem;
  color: var(--text-muted);
  font-weight: 600;
}

.experts-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.expert-chip {
  padding: 5px 12px;
  font-size: 0.74rem;
  background: #FFFFFF;
  border: 1px solid var(--border);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.chip-rose {
  border-color: #FECACA;
  color: var(--accent-rose);
}

.llm-badge-line {
  margin-top: 4px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 0.92rem;
  font-weight: 700;
  color: var(--text-main);
  letter-spacing: -0.01em;
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

.empty-evidence {
  padding: 20px;
  border-radius: 12px;
  text-align: center;
  font-size: 0.78rem;
  color: var(--text-muted);
  background: #F8FAFC;
  border: 1px solid var(--border);
}

.evidence-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.evidence-card {
  border-radius: 12px;
  padding: 12px 14px;
  background: #F8FAFC;
  border: 1px solid var(--border);
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.evidence-card:hover {
  background: #FFFFFF;
  border-color: #CBD5E1;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.06);
}

.evidence-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  gap: 10px;
}

.evidence-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  overflow: hidden;
}

.source-tag {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
  white-space: nowrap;
}

.src-guideline {
  background: #ECFDF5;
  color: #065F46;
  border: 1px solid #A7F3D0;
}
.src-drug {
  background: #EEF2FF;
  color: #4338CA;
  border: 1px solid #C7D2FE;
}
.src-paper {
  background: #F0FDFA;
  color: #0F766E;
  border: 1px solid #99F6E4;
}
.src-default {
  background: #F1F5F9;
  color: #475569;
  border: 1px solid #CBD5E1;
}

.evidence-title {
  font-size: 0.78rem;
  color: var(--text-main);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.evidence-right {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.72rem;
  color: var(--text-muted);
  flex-shrink: 0;
}

.score-badge {
  color: #B45309;
  font-weight: 700;
  background: #FFFBEB;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid #FDE68A;
}

.expand-icon {
  transition: transform 0.2s;
  color: var(--text-muted);
}

.expand-icon.is-expanded {
  transform: rotate(180deg);
}

.evidence-detail {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.evidence-badges {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.evidence-content-text {
  font-size: 0.78rem;
  color: var(--text-main);
  line-height: 1.6;
  background: #FFFFFF;
  border: 1px solid var(--border);
  padding: 10px 12px;
  border-radius: 8px;
}

.trace-stepper {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 380px;
  overflow-y: auto;
  padding-right: 4px;
}

.trace-step-item {
  display: flex;
  gap: 12px;
}

.step-indicator {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.step-circle {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 0.72rem;
  font-weight: 700;
}

.circle-primary {
  background: var(--primary-light);
  color: var(--primary);
  border: 1px solid #C7D2FE;
}
.circle-success {
  background: #ECFDF5;
  color: #059669;
  border: 1px solid #A7F3D0;
}
.circle-warning {
  background: #FFFBEB;
  color: #D97706;
  border: 1px solid #FDE68A;
}
.circle-danger {
  background: #FEF2F2;
  color: #DC2626;
  border: 1px solid #FECACA;
}

.step-line {
  width: 2px;
  flex: 1;
  background: var(--border);
  margin: 4px 0;
}

.step-body {
  flex: 1;
  border-radius: 10px;
  padding: 8px 12px;
  background: #F8FAFC;
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 6px;
  transition: all 0.2s ease;
}

.step-body:hover {
  background: #FFFFFF;
  border-color: #CBD5E1;
}

.step-name {
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--text-main);
}

.step-detail {
  font-size: 0.72rem;
  color: var(--text-muted);
  line-height: 1.4;
}
</style>
