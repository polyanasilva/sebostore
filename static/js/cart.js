// Carrinho persistido em localStorage
const CART_KEY = "sebo_cart_v1";

const Cart = {
  load() {
    try {
      return JSON.parse(localStorage.getItem(CART_KEY)) || [];
    } catch (_e) {
      return [];
    }
  },
  save(items) {
    localStorage.setItem(CART_KEY, JSON.stringify(items));
    Cart.updateBadge();
  },
  add(book) {
    const items = Cart.load();
    const existing = items.find((it) => it.id === book.id);
    if (existing) {
      existing.qty += 1;
    } else {
      items.push({ ...book, qty: 1 });
    }
    Cart.save(items);
  },
  remove(id) {
    Cart.save(Cart.load().filter((it) => it.id !== id));
  },
  setQty(id, qty) {
    const items = Cart.load();
    const it = items.find((i) => i.id === id);
    if (!it) return;
    it.qty = Math.max(1, parseInt(qty, 10) || 1);
    Cart.save(items);
  },
  clear() {
    localStorage.removeItem(CART_KEY);
    Cart.updateBadge();
  },
  totalQty() {
    return Cart.load().reduce((sum, it) => sum + it.qty, 0);
  },
  totalPrice() {
    return Cart.load().reduce((sum, it) => sum + it.qty * it.price, 0);
  },
  updateBadge() {
    const badge = document.getElementById("cart-badge");
    if (!badge) return;
    const total = Cart.totalQty();
    badge.textContent = total;
    badge.classList.toggle("visible", total > 0);
  },
};

function formatBRL(value) {
  return value.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function toast(msg) {
  let el = document.querySelector(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("visible");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("visible"), 2200);
}

// Botão "Adicionar" — funciona tanto no catálogo quanto no detalhe
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".add-to-cart");
  if (!btn) return;
  const book = {
    id: parseInt(btn.dataset.id, 10),
    title: btn.dataset.title,
    author: btn.dataset.author,
    price: parseFloat(btn.dataset.price),
    image: btn.dataset.image || "",
  };
  Cart.add(book);
  toast(`"${book.title}" adicionado ao carrinho`);
});

// Renderização do carrinho
function renderCart() {
  const itemsContainer = document.getElementById("cart-items");
  if (!itemsContainer) return;

  const items = Cart.load();
  const emptyEl = document.getElementById("cart-empty");
  const contentEl = document.getElementById("cart-content");

  if (items.length === 0) {
    emptyEl.style.display = "";
    contentEl.style.display = "none";
    return;
  }

  emptyEl.style.display = "none";
  contentEl.style.display = "";

  itemsContainer.innerHTML = items
    .map((it) => {
      const subtotal = it.qty * it.price;
      const img = it.image
        ? `<img src="/uploads/${it.image}" alt="${escapeHtml(it.title)}">`
        : `<div class="cart-item-cover-placeholder">📖</div>`;
      return `
        <div class="cart-item" data-id="${it.id}">
          <div class="cart-item-cover">${img}</div>
          <div class="cart-item-info">
            <h3>${escapeHtml(it.title)}</h3>
            <p class="cart-item-author">${escapeHtml(it.author)}</p>
            <p class="cart-item-price">${formatBRL(it.price)}</p>
          </div>
          <div class="cart-item-actions">
            <label class="qty-label">
              Qtd
              <input type="number" min="1" value="${it.qty}" class="qty-input" data-id="${it.id}">
            </label>
            <p class="cart-item-subtotal">${formatBRL(subtotal)}</p>
            <button class="btn-remove" data-id="${it.id}" title="Remover">✕</button>
          </div>
        </div>
      `;
    })
    .join("");

  document.getElementById("cart-total").textContent = formatBRL(Cart.totalPrice());
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Eventos do carrinho
document.addEventListener("click", (e) => {
  const removeBtn = e.target.closest(".btn-remove");
  if (removeBtn) {
    Cart.remove(parseInt(removeBtn.dataset.id, 10));
    renderCart();
  }
});

document.addEventListener("change", (e) => {
  const qtyInput = e.target.closest(".qty-input");
  if (qtyInput) {
    Cart.setQty(parseInt(qtyInput.dataset.id, 10), qtyInput.value);
    renderCart();
  }
});

// Checkout — envia para a API, salva pedido, abre WhatsApp
document.addEventListener("submit", async (e) => {
  const form = e.target.closest("#checkout-form");
  if (!form) return;
  e.preventDefault();

  const items = Cart.load();
  if (items.length === 0) {
    toast("Carrinho vazio");
    return;
  }

  const btn = document.getElementById("checkout-btn");
  btn.disabled = true;
  btn.textContent = "Enviando…";

  try {
    const res = await fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_name: document.getElementById("customer_name").value.trim(),
        items: items.map((it) => ({ id: it.id, qty: it.qty })),
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Erro ao processar pedido");

    Cart.clear();
    // Abre o WhatsApp e mostra confirmação
    window.location.href = data.whatsapp_url;
  } catch (err) {
    toast(err.message || "Erro ao finalizar pedido");
    btn.disabled = false;
    btn.textContent = "Finalizar pelo WhatsApp";
  }
});

// Inicialização
document.addEventListener("DOMContentLoaded", () => {
  Cart.updateBadge();
  renderCart();
});
