<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

const { t, currentCurrency, translateWarehouse } = useI18n()

const budget = ref(100000)
const recommendations = ref([])
const selectedSkus = ref(new Set())
const loading = ref(false)
const error = ref(null)
const submitting = ref(false)
const submitError = ref(null)
const confirmation = ref(null)

let debounceTimer = null
// Monotonic counter: only the response of the latest request may update state.
let requestSeq = 0

const loadRecommendations = async () => {
  const seq = ++requestSeq
  loading.value = true
  error.value = null
  try {
    const data = await api.getRestockRecommendations(budget.value)
    if (seq !== requestSeq) return // a newer request superseded this one
    recommendations.value = data
    // All recommended rows start selected
    selectedSkus.value = new Set(data.map(r => r.sku))
  } catch (err) {
    if (seq !== requestSeq) return
    recommendations.value = []
    selectedSkus.value = new Set()
    error.value = t('restocking.loadFailed', { message: err.message })
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

// Debounce slider input so dragging does not fire a request per step
watch(budget, () => {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(loadRecommendations, 250)
})

const selectedRows = computed(() =>
  recommendations.value.filter(r => selectedSkus.value.has(r.sku))
)
const selectedCount = computed(() => selectedRows.value.length)
const selectedTotal = computed(() =>
  selectedRows.value.reduce((sum, r) => sum + r.line_cost, 0)
)
const allSelected = computed(
  () => recommendations.value.length > 0 && selectedCount.value === recommendations.value.length
)

const toggleRow = (sku) => {
  // Replace the Set so the ref change is detected
  const next = new Set(selectedSkus.value)
  if (next.has(sku)) next.delete(sku)
  else next.add(sku)
  selectedSkus.value = next
}

const toggleAll = () => {
  selectedSkus.value = allSelected.value
    ? new Set()
    : new Set(recommendations.value.map(r => r.sku))
}

const money = (amount) => formatCurrency(amount, currentCurrency.value)
const moneyExact = (amount) => formatCurrencyWithDecimals(amount, currentCurrency.value, 2)
const percent = (value) => `${Math.round(value * 100)}%`

const formatDate = (value) => {
  const d = new Date(value)
  if (isNaN(d.getTime())) return value
  return d.toLocaleDateString(currentCurrency.value === 'JPY' ? 'ja-JP' : 'en-US', {
    year: 'numeric', month: 'short', day: 'numeric'
  })
}

const placeOrder = async () => {
  if (submitting.value || selectedCount.value === 0) return
  submitting.value = true
  submitError.value = null
  confirmation.value = null
  try {
    // Server recomputes costs; send only sku and quantity
    const lines = selectedRows.value.map(r => ({ sku: r.sku, quantity: r.shortfall }))
    const order = await api.placeRestockOrder(lines)
    confirmation.value = t('restocking.orderPlaced', {
      id: order.id,
      date: formatDate(order.expected_delivery)
    })
    await loadRecommendations()
  } catch (err) {
    console.error(err)
    const detail = err.response?.data?.detail
    submitError.value = t('restocking.orderFailed', {
      message: typeof detail === 'string' ? detail : err.message
    })
  } finally {
    submitting.value = false
  }
}

onMounted(loadRecommendations)
onBeforeUnmount(() => clearTimeout(debounceTimer))
</script>

<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div class="card budget-card">
      <label class="budget-label" for="restock-budget">{{ t('restocking.budget') }}</label>
      <input
        id="restock-budget"
        v-model.number="budget"
        type="range"
        min="0"
        max="500000"
        step="10000"
        class="budget-slider"
      />
      <span class="budget-value">{{ money(budget) }}</span>
    </div>

    <div v-if="confirmation" class="message success-message" role="status">{{ confirmation }}</div>
    <div v-if="submitError" class="message error-message" role="alert">{{ submitError }}</div>

    <div v-if="loading && recommendations.length === 0" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else class="card">
      <div class="card-header summary-bar">
        <div class="summary-item">
          <span class="summary-label">{{ t('restocking.selectedCount') }}</span>
          <strong>{{ selectedCount }}</strong>
        </div>
        <div class="summary-item">
          <span class="summary-label">{{ t('restocking.selectedTotal') }}</span>
          <strong>{{ money(selectedTotal) }}</strong>
        </div>
        <button
          type="button"
          class="place-order-btn"
          :disabled="selectedCount === 0 || submitting"
          @click="placeOrder"
        >
          {{ submitting ? t('restocking.submitting') : t('restocking.placeOrder') }}
        </button>
      </div>

      <div v-if="recommendations.length === 0" class="empty-state">
        {{ t('restocking.noRecommendations') }}
      </div>
      <div v-else class="table-container" :class="{ stale: loading }">
        <table>
          <thead>
            <tr>
              <th class="col-check">
                <input type="checkbox" :checked="allSelected" @change="toggleAll" />
              </th>
              <th>{{ t('restocking.table.sku') }}</th>
              <th>{{ t('restocking.table.name') }}</th>
              <th>{{ t('restocking.table.warehouse') }}</th>
              <th>{{ t('restocking.table.onHand') }}</th>
              <th>{{ t('restocking.table.forecast') }}</th>
              <th>{{ t('restocking.table.shortfall') }}</th>
              <th>{{ t('restocking.table.unitCost') }}</th>
              <th>{{ t('restocking.table.lineCost') }}</th>
              <th>{{ t('restocking.table.urgency') }}</th>
              <th>{{ t('restocking.table.leadTime') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in recommendations" :key="row.sku">
              <td class="col-check">
                <input
                  type="checkbox"
                  :checked="selectedSkus.has(row.sku)"
                  :aria-label="t('restocking.selectRow', { sku: row.sku })"
                  @change="toggleRow(row.sku)"
                />
              </td>
              <td><strong>{{ row.sku }}</strong></td>
              <td>{{ row.name }}</td>
              <td>{{ translateWarehouse(row.warehouse) }}</td>
              <td>{{ row.quantity_on_hand }}</td>
              <td>{{ row.forecasted_demand }}</td>
              <td>{{ row.shortfall }}</td>
              <td>{{ moneyExact(row.unit_cost) }}</td>
              <td><strong>{{ money(row.line_cost) }}</strong></td>
              <td>{{ percent(row.urgency) }}</td>
              <td>{{ row.lead_time_days ?? '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.budget-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.5rem;
  margin-bottom: 1.5rem;
}

.budget-label {
  font-weight: 600;
  color: #0f172a;
}

.budget-slider {
  flex: 1;
  max-width: 480px;
}

.budget-value {
  min-width: 96px;
  font-weight: 600;
  color: #0f172a;
}

.summary-bar {
  display: flex;
  align-items: center;
  gap: 2rem;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  color: #0f172a;
}

.summary-label {
  font-size: 0.813rem;
  color: #64748b;
}

.place-order-btn {
  margin-left: auto;
  padding: 0.5rem 1.25rem;
  background: #0f172a;
  color: white;
  border: 1px solid #0f172a;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
}

.place-order-btn:disabled {
  background: #e2e8f0;
  border-color: #e2e8f0;
  color: #64748b;
  cursor: not-allowed;
}

.col-check {
  width: 40px;
}

.stale {
  opacity: 0.6;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}

.message {
  padding: 0.75rem 1rem;
  border-radius: 6px;
  margin-bottom: 1rem;
  border: 1px solid #e2e8f0;
}

.success-message {
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #166534;
}

.error-message {
  background: #fef2f2;
  border-color: #fecaca;
  color: #991b1b;
}
</style>
