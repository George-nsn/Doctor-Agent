<template>
  <el-dialog
    v-model="visible"
    title="大模型引擎与 API 密钥设置"
    width="600px"
    destroy-on-close
    :close-on-click-modal="false"
    class="neu-modal"
  >
    <div v-loading="loading" class="settings-dialog-body">
      <!-- 调度配置 -->
      <div class="neu-inset-sm form-section">
        <div class="form-grid">
          <div class="form-item">
            <label class="item-label font-display">首选大模型 (Primary Provider)</label>
            <div class="select-well neu-inset-sm">
              <select v-model="form.primary_provider" class="neu-select font-display">
                <option value="deepseek">DeepSeek (深度求索)</option>
                <option value="glm">智谱 GLM (清言)</option>
                <option value="openai">OpenAI (GPT-4o 系列)</option>
                <option value="gemini">Google Gemini</option>
              </select>
            </div>
          </div>

          <div class="form-item">
            <label class="item-label font-display">故障转移容灾链 (Failover Chain)</label>
            <input
              v-model="form.failover_providers"
              class="neu-input font-display"
              placeholder="例如: deepseek,glm,openai"
            />
          </div>
        </div>
      </div>

      <!-- 厂商标签切换 -->
      <div class="tabs-nav font-display">
        <button
          v-for="tab in ['deepseek', 'glm', 'openai', 'gemini']"
          :key="tab"
          class="tab-btn"
          :class="{ active: activeTab === tab }"
          @click="activeTab = tab"
        >
          <span class="neu-glow-dot" :class="providersData[tab]?.has_key ? 'emerald' : 'muted-dot'"></span>
          <span>{{ formatTabName(tab) }}</span>
        </button>
      </div>

      <!-- 各厂商具体表单 -->
      <div class="tab-content neu-inset-sm">
        <!-- DeepSeek -->
        <div v-if="activeTab === 'deepseek'" class="provider-form">
          <div class="form-group">
            <label>API Key (DeepSeek):</label>
            <input
              v-model="form.deepseek.api_key"
              type="password"
              class="neu-input"
              :placeholder="providersData.deepseek?.has_key ? `已配置 (${providersData.deepseek.masked_key})，输入新Key覆盖` : 'sk-...'"
            />
          </div>
          <div class="form-group">
            <label>Base URL:</label>
            <input v-model="form.deepseek.base_url" class="neu-input" placeholder="https://api.deepseek.com" />
          </div>
          <div class="form-group">
            <label>模型名称:</label>
            <input v-model="form.deepseek.model" class="neu-input" placeholder="deepseek-chat" />
          </div>
        </div>

        <!-- 智谱 GLM -->
        <div v-if="activeTab === 'glm'" class="provider-form">
          <div class="form-group">
            <label>API Key (智谱清言):</label>
            <input
              v-model="form.glm.api_key"
              type="password"
              class="neu-input"
              :placeholder="providersData.glm?.has_key ? `已配置 (${providersData.glm.masked_key})，输入新Key覆盖` : '请输入智谱 API Key'"
            />
          </div>
          <div class="form-group">
            <label>Base URL:</label>
            <input v-model="form.glm.base_url" class="neu-input" placeholder="https://open.bigmodel.cn/api/paas/v4" />
          </div>
          <div class="form-group">
            <label>模型名称:</label>
            <input v-model="form.glm.model" class="neu-input" placeholder="glm-4-flash" />
          </div>
        </div>

        <!-- OpenAI -->
        <div v-if="activeTab === 'openai'" class="provider-form">
          <div class="form-group">
            <label>API Key (OpenAI):</label>
            <input
              v-model="form.openai.api_key"
              type="password"
              class="neu-input"
              :placeholder="providersData.openai?.has_key ? `已配置 (${providersData.openai.masked_key})，输入新Key覆盖` : 'sk-...'"
            />
          </div>
          <div class="form-group">
            <label>Base URL:</label>
            <input v-model="form.openai.base_url" class="neu-input" placeholder="https://api.openai.com/v1" />
          </div>
          <div class="form-group">
            <label>模型名称:</label>
            <input v-model="form.openai.model" class="neu-input" placeholder="gpt-4o-mini" />
          </div>
        </div>

        <!-- Google Gemini -->
        <div v-if="activeTab === 'gemini'" class="provider-form">
          <div class="form-group">
            <label>API Key (Google AI Studio):</label>
            <input
              v-model="form.gemini.api_key"
              type="password"
              class="neu-input"
              :placeholder="providersData.gemini?.has_key ? `已配置 (${providersData.gemini.masked_key})，输入新Key覆盖` : 'AIza...'"
            />
          </div>
          <div class="form-group">
            <label>Base URL:</label>
            <input v-model="form.gemini.base_url" class="neu-input" placeholder="https://generativelanguage.googleapis.com/v1beta" />
          </div>
          <div class="form-group">
            <label>模型名称:</label>
            <input v-model="form.gemini.model" class="neu-input" placeholder="gemini-2.5-flash" />
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <button class="neu-action-btn font-display" @click="visible = false">取消</button>
        <button class="neu-primary-btn font-display" :disabled="saving" @click="handleSave">
          <el-icon v-if="saving" class="is-loading"><Loading /></el-icon>
          <span>保存并即时生效</span>
        </button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api.js'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:modelValue', 'saved'])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const activeTab = ref('deepseek')
const loading = ref(false)
const saving = ref(false)
const providersData = ref({})

const form = reactive({
  primary_provider: 'deepseek',
  failover_providers: 'deepseek,glm,openai',
  deepseek: { api_key: '', base_url: '', model: '' },
  glm: { api_key: '', base_url: '', model: '' },
  openai: { api_key: '', base_url: '', model: '' },
  gemini: { api_key: '', base_url: '', model: '' }
})

const formatTabName = (tab) => {
  const map = {
    deepseek: 'DeepSeek',
    glm: '智谱 GLM',
    openai: 'OpenAI',
    gemini: 'Gemini'
  }
  return map[tab] || tab
}

const loadSettings = async () => {
  loading.value = true
  try {
    const data = await api.getSettings()
    form.primary_provider = data.primary_provider || 'deepseek'
    form.failover_providers = data.failover_providers || 'deepseek,glm,openai'
    providersData.value = data.providers || {}

    if (data.providers?.deepseek) {
      form.deepseek.base_url = data.providers.deepseek.base_url
      form.deepseek.model = data.providers.deepseek.model
    }
    if (data.providers?.glm) {
      form.glm.base_url = data.providers.glm.base_url
      form.glm.model = data.providers.glm.model
    }
    if (data.providers?.openai) {
      form.openai.base_url = data.providers.openai.base_url
      form.openai.model = data.providers.openai.model
    }
    if (data.providers?.gemini) {
      form.gemini.base_url = data.providers.gemini.base_url
      form.gemini.model = data.providers.gemini.model
    }
  } catch (err) {
    ElMessage.error('获取模型设置失败，请检查服务状态')
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    const payload = {
      primary_provider: form.primary_provider,
      failover_providers: form.failover_providers,
      deepseek: {
        api_key: form.deepseek.api_key || null,
        base_url: form.deepseek.base_url || null,
        model: form.deepseek.model || null
      },
      glm: {
        api_key: form.glm.api_key || null,
        base_url: form.glm.base_url || null,
        model: form.glm.model || null
      },
      openai: {
        api_key: form.openai.api_key || null,
        base_url: form.openai.base_url || null,
        model: form.openai.model || null
      },
      gemini: {
        api_key: form.gemini.api_key || null,
        base_url: form.gemini.base_url || null,
        model: form.gemini.model || null
      }
    }
    await api.updateSettings(payload)
    ElMessage.success('大模型引擎与 API 密钥已保存，即时生效！')
    visible.value = false
    emit('saved')
  } catch (err) {
    ElMessage.error('保存设置失败: ' + err.message)
  } finally {
    saving.value = false
  }
}

watch(visible, (val) => {
  if (val) {
    loadSettings()
  }
})
</script>

<style scoped>
:deep(.el-dialog) {
  background: #FFFFFF;
  border-radius: 20px;
  box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.2), 0 0 0 1px var(--border);
  border: none;
  padding: 24px;
}

:deep(.el-dialog__header) {
  margin-right: 0;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

:deep(.el-dialog__title) {
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 1.15rem;
  color: var(--text-main);
  letter-spacing: -0.01em;
}

.settings-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-top: 16px;
}

.form-section {
  border-radius: 14px;
  padding: 16px;
  background: #F8FAFC;
  border: 1px solid var(--border);
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.item-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-muted);
}

.select-well {
  border-radius: 8px;
  background: #FFFFFF;
  border: 1px solid var(--border);
  padding: 0 8px;
  transition: all 0.2s ease;
}

.select-well:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.12);
}

.neu-select {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  font-size: 0.82rem;
  color: var(--text-main);
  padding: 8px 4px;
  font-weight: 500;
}

.neu-input {
  width: 100%;
  background: #FFFFFF;
  border: 1px solid var(--border);
  outline: none;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 0.82rem;
  color: var(--text-main);
  transition: all 0.2s ease;
}

.neu-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.12);
}

.tabs-nav {
  display: flex;
  gap: 8px;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  border-radius: 9999px;
  background: #FFFFFF;
  border: 1px solid var(--border);
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-muted);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.2s ease;
}

.tab-btn:hover {
  border-color: #CBD5E1;
  color: var(--text-main);
}

.tab-btn.active {
  background: var(--primary-light);
  border-color: #C7D2FE;
  color: var(--primary);
}

.muted-dot {
  background: #94A3B8;
}

.tab-content {
  border-radius: 14px;
  padding: 18px;
  background: #F8FAFC;
  border: 1px solid var(--border);
}

.provider-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-muted);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

.neu-action-btn {
  padding: 9px 18px;
  border-radius: 8px;
  background: #FFFFFF;
  border: 1px solid var(--border);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  cursor: pointer;
  font-weight: 600;
  font-size: 0.82rem;
  color: var(--text-muted);
  transition: all 0.2s ease;
}

.neu-action-btn:hover {
  background: #F8FAFC;
  color: var(--text-main);
  border-color: #CBD5E1;
}

.neu-action-btn:active {
  transform: translateY(0);
}

.neu-primary-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 22px;
  border-radius: 8px;
  background: var(--grad);
  color: #ffffff;
  border: none;
  cursor: pointer;
  font-weight: 700;
  font-size: 0.84rem;
  box-shadow: var(--shadow-btn);
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.neu-primary-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 22px 0 rgba(79, 70, 229, 0.42);
}

.neu-primary-btn:active {
  transform: translateY(0);
}
</style>
