document.addEventListener("DOMContentLoaded", () => {
  const signupError = document.querySelector("[data-signup-error]");
  if (signupError) {
    const closeButton = signupError.querySelector("[data-signup-error-close]");
    const dismissError = () => signupError.remove();
    closeButton?.addEventListener("click", dismissError);
    signupError.addEventListener("click", (event) => {
      if (event.target === signupError) dismissError();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") dismissError();
    }, { once: true });
    closeButton?.focus();
  }

  document.querySelectorAll("[data-cancel-order]").forEach((button) => {
    button.addEventListener("click", (event) => {
      if (!window.confirm("Cancel this order? You can only cancel before payment.")) {
        event.preventDefault();
      }
    });
  });

  const flashPopup = document.querySelector("[data-flash-popup]");
  if (flashPopup) {
    const closeButtons = flashPopup.querySelectorAll("[data-popup-close]");
    const dismissPopup = () => {
      flashPopup.remove();
      document.removeEventListener("keydown", dismissOnEscape);
    };
    const dismissOnEscape = (event) => {
      if (event.key === "Escape") dismissPopup();
    };
    closeButtons.forEach((button) => button.addEventListener("click", dismissPopup));
    flashPopup.addEventListener("click", (event) => {
      if (event.target === flashPopup) dismissPopup();
    });
    document.addEventListener("keydown", dismissOnEscape);
    closeButtons[0]?.focus();
  }

  const filePreviewModal = document.querySelector("[data-file-preview-modal]");
  if (filePreviewModal) {
    const previewDialog = filePreviewModal.querySelector(".file-preview-dialog");
    const previewTitle = filePreviewModal.querySelector("[data-file-preview-title]");
    const previewHint = filePreviewModal.querySelector("[data-file-preview-hint]");
    const previewContent = filePreviewModal.querySelector("[data-file-preview-content]");
    const previewDownload = filePreviewModal.querySelector("[data-file-preview-download]");
    let previousFocus = null;
    const closePreview = () => {
      filePreviewModal.hidden = true;
      previewContent.replaceChildren();
      document.body.classList.remove("file-preview-open");
      previousFocus?.focus();
      previousFocus = null;
    };
    const closeButtons = filePreviewModal.querySelectorAll("[data-file-preview-close]");
    closeButtons.forEach((button) => button.addEventListener("click", closePreview));
    filePreviewModal.addEventListener("click", (event) => {
      if (event.target === filePreviewModal) closePreview();
    });
    document.addEventListener("keydown", (event) => {
      if (filePreviewModal.hidden) return;
      if (event.key === "Escape") closePreview();
      if (event.key === "Tab") {
        const focusable = [...filePreviewModal.querySelectorAll("a[href], button:not([disabled])")];
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    });
    document.addEventListener("click", (event) => {
      const previewLink = event.target.closest("[data-file-preview]");
      if (!previewLink) return;
      event.preventDefault();
      previousFocus = previewLink;
      const fileName = previewLink.dataset.fileName || "File preview";
      const extension = fileName.split(".").pop().toLowerCase();
      previewTitle.textContent = fileName;
      previewContent.replaceChildren();
      const downloadLink = previewLink.parentElement.querySelector(".admin-file-download");
      const downloadUrl = new URL(previewLink.href);
      downloadUrl.searchParams.delete("preview");
      previewDownload.href = downloadLink?.href || downloadUrl.href;
      previewHint.textContent = "";
      if (extension === "pdf") {
        const frame = document.createElement("iframe");
        frame.className = "file-preview-frame";
        frame.src = previewLink.href;
        frame.title = `Preview of ${fileName}`;
        previewContent.append(frame);
        previewHint.textContent = "PDF preview";
      } else if (["jpg", "jpeg", "png"].includes(extension)) {
        const image = document.createElement("img");
        image.className = "file-preview-image";
        image.src = previewLink.href;
        image.alt = fileName;
        previewContent.append(image);
        previewHint.textContent = "Image preview";
      } else {
        const message = document.createElement("p");
        message.className = "file-preview-unavailable";
        message.textContent = "This document format cannot be previewed in the browser. Download the file to view it.";
        previewContent.append(message);
        previewHint.textContent = "Preview not available";
      }
      filePreviewModal.hidden = false;
      document.body.classList.add("file-preview-open");
      closeButtons[0]?.focus();
    });
  }

  const isAndroid = /Android/i.test(navigator.userAgent);
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  document.querySelectorAll("[data-upi-android-href], [data-upi-ios-href]").forEach((link) => {
    if (isAndroid && link.dataset.upiAndroidHref) {
      link.href = link.dataset.upiAndroidHref;
    } else if (isIOS && link.dataset.upiIosHref) {
      link.href = link.dataset.upiIosHref;
    }
  });

  document.querySelectorAll("[data-item-quote-form]").forEach((form) => {
    const itemQuotes = Array.from(form.querySelectorAll("[data-item-quote]"));
    const chargeInputs = Array.from(form.querySelectorAll("[data-quote-charge]"));
    const itemsTotal = form.querySelector("[data-quote-items-total]");
    const additionalChargesTotal = form.querySelector("[data-additional-charges-total]");
    const deliveryChargesTotal = form.querySelector("[data-delivery-charges-total]");
    const grandTotal = form.querySelector("[data-quote-grand-total]");
    const updateQuoteTotal = () => {
      const amounts = itemQuotes.map((input) => Number(input.value));
      const charges = chargeInputs.map((input) => input.value.trim() === "" ? 0 : Number(input.value));
      const allValid = amounts.length > 0
        && amounts.every((amount) => Number.isFinite(amount) && amount > 0)
        && charges.every((amount) => Number.isFinite(amount) && amount >= 0);
      if (!allValid) {
        itemsTotal.textContent = "Enter item prices";
        grandTotal.textContent = "Enter item prices";
        return;
      }
      const itemTotal = amounts.reduce((sum, amount) => sum + amount, 0);
      const additionalCharges = charges[0] || 0;
      const deliveryCharges = charges[1] || 0;
      itemsTotal.textContent = `₹${itemTotal.toFixed(2)}`;
      additionalChargesTotal.textContent = `₹${additionalCharges.toFixed(2)}`;
      deliveryChargesTotal.textContent = `₹${deliveryCharges.toFixed(2)}`;
      grandTotal.textContent = `₹${(itemTotal + additionalCharges + deliveryCharges).toFixed(2)}`;
    };
    itemQuotes.forEach((input) => input.addEventListener("input", updateQuoteTotal));
    chargeInputs.forEach((input) => input.addEventListener("input", updateQuoteTotal));
    updateQuoteTotal();
  });
  document.querySelectorAll("[data-order-filter]").forEach((select) => {
    select.addEventListener("change", () => select.form?.requestSubmit());
  });

  const fileInput = document.querySelector("#documents");
  const fileLabel = document.querySelector("[data-file-name]");
  const fileList = document.querySelector("[data-file-list]");
  const dropZone = document.querySelector("[data-drop-zone]");
  let selectedFiles = [];

  const renderSelectedFiles = () => {
    fileLabel.textContent = selectedFiles.length
      ? `${selectedFiles.length} file${selectedFiles.length === 1 ? "" : "s"} selected — add more`
      : "Choose documents";
    fileList.replaceChildren();
    const fragment = document.createDocumentFragment();
    selectedFiles.forEach((file, index) => {
      const item = document.createElement("li");
      const name = document.createElement("span");
      const remove = document.createElement("button");
      name.textContent = file.name;
      remove.type = "button";
      remove.className = "remove-selected-file";
      remove.textContent = "Delete";
      remove.setAttribute("aria-label", `Delete ${file.name}`);
      remove.addEventListener("click", () => {
        selectedFiles.splice(index, 1);
        renderSelectedFiles();
        orderForm?.dispatchEvent(new Event("files-updated"));
      });
      item.append(name, remove);
      fragment.append(item);
    });
    fileList.append(fragment);
    fileList.hidden = selectedFiles.length === 0;
    fileInput.closest(".upload-zone")?.classList.toggle("has-file", selectedFiles.length > 0);
    fileInput.required = false;
  };

  if (fileInput && fileLabel) {
    const addSelectedFiles = (files) => {
      Array.from(files).forEach((file) => {
        const alreadySelected = selectedFiles.some((selected) =>
          selected.name === file.name &&
          selected.size === file.size &&
          selected.lastModified === file.lastModified
        );
        if (!alreadySelected) selectedFiles.push(file);
      });
      renderSelectedFiles();
      orderForm?.dispatchEvent(new Event("files-updated"));
    };

    fileInput.addEventListener("change", () => {
      addSelectedFiles(fileInput.files);
    });

    if (dropZone) {
      ["dragenter", "dragover"].forEach((eventName) => {
        dropZone.addEventListener(eventName, (event) => {
          event.preventDefault();
          event.stopPropagation();
          dropZone.classList.add("is-dragging");
        });
      });
      ["dragleave", "dragend"].forEach((eventName) => {
        dropZone.addEventListener(eventName, (event) => {
          event.preventDefault();
          if (eventName === "dragend" || !dropZone.contains(event.relatedTarget)) {
            dropZone.classList.remove("is-dragging");
          }
        });
      });
      dropZone.addEventListener("drop", (event) => {
        event.preventDefault();
        event.stopPropagation();
        dropZone.classList.remove("is-dragging");
        if (event.dataTransfer?.files.length) {
          addSelectedFiles(event.dataTransfer.files);
        }
      });
    }
  }

  const orderForm = document.querySelector("[data-order-form]");
  if (orderForm) {
    const priceData = JSON.parse(document.querySelector("#digital-price-data")?.textContent || "{}");
    const categoryInputs = orderForm.querySelectorAll("[data-cart-field='product_category']");
    const deliveryInputs = orderForm.querySelectorAll("[name='delivery_type']");
    const digitalFields = orderForm.querySelectorAll("[data-digital-field]");
    const cadFields = orderForm.querySelectorAll("[data-cad-field]");
    const cadSize = orderForm.querySelector("#cad_size");
    const paperType = orderForm.querySelector("#paper_type");
    const deliveryAddressField = orderForm.querySelector("[data-delivery-address]");
    const deliveryAddressChoice = orderForm.querySelector("[data-address-choice]");
    const newAddressField = orderForm.querySelector("[data-new-address-field]");
    const deliveryAddress = orderForm.querySelector("#delivery_address");
    const saveAddress = orderForm.querySelector("[name='save_address']");
    const notes = orderForm.querySelector("[data-order-notes]");
    const notesLabel = orderForm.querySelector("[data-notes-label]");
    const notesOptional = notesLabel.querySelector(".optional");
    const notesHint = orderForm.querySelector("[data-notes-hint]");
    const pricePreview = orderForm.querySelector("[data-price-preview]");
    const priceTotal = orderForm.querySelector("[data-price-total]");
    const priceUnit = orderForm.querySelector("[data-price-unit]");
    const priceHint = orderForm.querySelector("[data-price-hint]");
    const orderHelp = orderForm.querySelector("[data-order-help]");
    const submitButton = orderForm.querySelector("[data-order-submit]");
    const addCartItemButton = orderForm.querySelector("[data-add-cart-item]");
    const cartList = orderForm.querySelector("[data-cart-list]");
    const cartCount = orderForm.querySelector("[data-cart-count]");
    const cartCountInput = orderForm.querySelector("[data-cart-count-input]");
    const cartTotal = orderForm.querySelector("[data-cart-total]");
    const cartEmpty = orderForm.querySelector("[data-cart-empty]");
    const cartDeliveryNote = orderForm.querySelector("[data-cart-delivery-note]");
    const cart = [];
    const quantity = orderForm.querySelector("[data-price-qty]");
    const sizeSelect = orderForm.querySelector("[data-price-size]");
    const modeSelect = orderForm.querySelector("[data-price-mode]");
    const sidesSelect = orderForm.querySelector("[data-price-sides]");
    const sizeInfoTitle = orderForm.querySelector("[data-size-info-title]");
    const sizeInfoText = orderForm.querySelector("[data-size-info-text]");

    const selectedCategory = () => orderForm.querySelector("[data-cart-field='product_category']:checked")?.value;
    const buildCurrentItemData = () => {
      const category = selectedCategory();
      const copies = Number(quantity.value);
      if (
        !selectedFiles.length ||
        cart.length >= 50 ||
        !Number.isInteger(copies) ||
        copies < 1 ||
        copies > 1000
      ) return null;

      const itemData = {
        product_category: category,
        copies: String(copies),
        paper_size: category === "cad" ? cadSize.value : sizeSelect.value,
        print_type: category === "cad" ? "cad" : modeSelect.value,
        print_sides: category === "cad" ? "" : sidesSelect.value,
        cad_size: cadSize.value,
        paper_type: category === "cad" ? paperType.value : "",
        notes: notes.value.trim(),
        files: [...selectedFiles],
        estimate_paise: null,
      };
      if (category === "cad" && itemData.paper_size === "Custom" && !itemData.notes) return null;
      if (category === "digital_printing") {
        const rate = priceData[itemData.paper_size]?.[itemData.print_type]?.[itemData.print_sides];
        if (!rate || rate <= 0) return null;
        const sheetCount = itemData.print_sides === "front_back"
          ? Math.ceil(itemData.files.length / 2)
          : itemData.files.length;
        itemData.estimate_paise = rate * copies * sheetCount;
      }
      return itemData;
    };
    const createCartPayload = (itemData, index) => {
      const payload = document.createElement("div");
      payload.hidden = true;
      const addHiddenField = (name, value) => {
        const field = document.createElement("input");
        field.type = "hidden";
        field.dataset.cartFieldName = name;
        field.name = `cart_items[${index}][${name}]`;
        field.value = value;
        payload.append(field);
      };
      Object.entries(itemData).forEach(([key, value]) => {
        if (key !== "files" && key !== "estimate_paise") addHiddenField(key, value);
      });
      const uploads = document.createElement("input");
      uploads.type = "file";
      uploads.dataset.cartFieldName = "documents";
      uploads.name = `cart_items[${index}][documents]`;
      uploads.multiple = true;
      uploads.hidden = true;
      const transfer = new DataTransfer();
      itemData.files.forEach((file) => transfer.items.add(file));
      uploads.files = transfer.files;
      payload.append(uploads);
      return payload;
    };
    const updateCart = () => {
      let digitalEstimate = 0;
      let hasCad = false;
      let hasDigital = false;
      cart.forEach((item) => {
        if (item.estimate_paise === null) hasCad = true;
        else {
          hasDigital = true;
          digitalEstimate += item.estimate_paise;
        }
      });
      const deliveryType = orderForm.querySelector("[name='delivery_type']:checked")?.value;
      const deliveryFee = deliveryType === "delivery" ? Number(priceData.delivery_fee_paise || 0) : 0;
      const total = digitalEstimate + deliveryFee;
      cartCount.textContent = String(cart.length);
      cartCountInput.value = String(cart.length);
      cartEmpty.hidden = cart.length > 0;
      cartDeliveryNote.hidden = cart.length === 0 || deliveryType !== "delivery";
      cartTotal.textContent = cart.length === 0
        ? "No items added"
        : hasCad && !hasDigital
          ? "CAD quote required"
          : `${hasCad ? "Digital estimate" : "Estimated total"}: ₹${(total / 100).toFixed(2)}${hasCad ? " + CAD quote" : ""}`;
      submitButton.disabled = cart.length === 0 && !buildCurrentItemData();
    };
    const createCartRow = (item, index) => {
      const listItem = document.createElement("li");
      const summary = document.createElement("div");
      const title = document.createElement("strong");
      const detail = document.createElement("span");
      const remove = document.createElement("button");
      const itemCategory = item.product_category === "cad" ? "CAD drawing" : "Digital printing";
      const amount = item.estimate_paise === null
        ? "Quote required"
        : `₹${(item.estimate_paise / 100).toFixed(2)}`;
      title.textContent = `${itemCategory} · ${item.paper_size} · ${item.files.length} file${item.files.length === 1 ? "" : "s"}`;
      const copies = Number(item.copies);
      const paperType = item.product_category === "cad" ? ` · ${item.paper_type}` : "";
      detail.textContent = `${copies} print${copies === 1 ? "" : "s"} per file${paperType} · ${amount}`;
      remove.type = "button";
      remove.className = "remove-selected-file";
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", `Remove cart item ${index + 1}`);
      remove.addEventListener("click", () => {
        item.payload.remove();
        cart.splice(index, 1);
        renderCart();
        orderForm.dispatchEvent(new Event("cart-updated"));
      });
      summary.append(title, detail);
      listItem.append(summary, remove);
      return listItem;
    };
    const resetItemComposer = () => {
      selectedFiles = [];
      fileInput.value = "";
      categoryInputs.forEach((input) => {
        input.checked = input.value === "cad";
      });
      quantity.value = "1";
      sizeSelect.selectedIndex = 0;
      modeSelect.selectedIndex = 0;
      sidesSelect.selectedIndex = 0;
      cadSize.selectedIndex = 0;
      paperType.selectedIndex = 0;
      notes.value = "";
      renderSelectedFiles();
    };
    const renderCart = () => {
      const fragment = document.createDocumentFragment();
      cart.forEach((item, index) => {
        item.payload.querySelectorAll("[name]").forEach((field) => {
          field.name = `cart_items[${index}][${field.dataset.cartFieldName}]`;
        });
        fragment.append(createCartRow(item, index));
      });
      cartList.replaceChildren(fragment);
      updateCart();
    };
    const addItemToCart = async () => {
      const itemData = buildCurrentItemData();
      if (!itemData) return;
      addCartItemButton.disabled = true;
      const addCartItemLabel = addCartItemButton.querySelector("[data-add-cart-label]");
      addCartItemButton.setAttribute("aria-busy", "true");
      addCartItemLabel.textContent = "Adding item to cart";
      await new Promise((resolve) => requestAnimationFrame(resolve));
      try {
        const payload = createCartPayload(itemData, cart.length);
        orderForm.append(payload);
        const addedItem = { ...itemData, payload };
        cart.push(addedItem);
        cartList.append(createCartRow(addedItem, cart.length - 1));
        resetItemComposer();
      } finally {
        addCartItemLabel.textContent = "Add item to cart";
        addCartItemButton.removeAttribute("aria-busy");
        updateOrderForm();
      }
    };

    const updateOrderForm = () => {
      const category = selectedCategory();
      const isDigital = category === "digital_printing";
      const deliveryType = orderForm.querySelector("[name='delivery_type']:checked")?.value;
      const isDelivery = deliveryType === "delivery";
      const isCustomCad = !isDigital && cadSize.value === "Custom";
      digitalFields.forEach((field) => {
        field.hidden = !isDigital;
        field.querySelector("select").disabled = !isDigital;
      });
      cadFields.forEach((field) => {
        field.hidden = isDigital;
        field.querySelector("select").disabled = isDigital;
      });
      deliveryAddressField.hidden = !isDelivery;
      deliveryAddressChoice.disabled = !isDelivery;
      const isNewAddress = deliveryAddressChoice.value === "__new__";
      newAddressField.hidden = !isDelivery || !isNewAddress;
      deliveryAddress.disabled = !isDelivery || !isNewAddress;
      deliveryAddress.required = isDelivery && isNewAddress;
      saveAddress.disabled = !isDelivery || !isNewAddress;
      notesHint.hidden = !isCustomCad;
      notesOptional.hidden = isCustomCad;
      notesLabel.firstChild.textContent = isCustomCad ? "Extra notes (required) " : "Anything we should know ";
      pricePreview.hidden = !isDigital;
      const selectedSize = sizeSelect.selectedOptions[0];
      sizeInfoTitle.textContent = selectedSize.textContent;
      sizeInfoText.textContent = selectedSize.dataset.description;

      if (!isDigital) {
        orderHelp.textContent = isDelivery
          ? "CAD delivery charges will be included in the quotation."
          : "CAD orders are quoted by the print desk.";
        addCartItemButton.disabled = !selectedFiles.length
          || cart.length >= 50
          || !Number.isInteger(Number(quantity.value))
          || Number(quantity.value) < 1
          || Number(quantity.value) > 1000
          || (isCustomCad && !notes.value.trim());
        submitButton.disabled = cart.length === 0;
        updateCart();
        return;
      }

      orderHelp.textContent = sidesSelect.value === "front_back"
        ? "Front and back uses two files per sheet; any odd final file uses one side."
        : "Estimate = files × prints per file × configured rate.";
      const sheetRate = priceData[sizeSelect.value]?.[modeSelect.value]?.[sidesSelect.value];
      const copies = Number(quantity.value);
      const fileCount = selectedFiles.length;
      if (!sheetRate || !Number.isInteger(copies) || copies < 1 || copies > 1000 || fileCount < 1) {
        priceTotal.textContent = "Rate not set";
        priceUnit.textContent = "";
        priceHint.textContent = fileCount < 1
          ? "Select at least one file to see the estimate."
          : "The print desk needs to configure this size and print mode.";
        addCartItemButton.disabled = true;
        submitButton.disabled = cart.length === 0;
        updateCart();
        return;
      }

      const sheetsPerCopy = sidesSelect.value === "front_back"
        ? Math.ceil(fileCount / 2)
        : fileCount;
      const total = sheetRate * copies * sheetsPerCopy;
      priceTotal.textContent = `₹${(total / 100).toFixed(2)}`;
      priceUnit.textContent = `₹${(sheetRate / 100).toFixed(2)} per sheet`;
      priceHint.textContent = `${sheetsPerCopy} sheet${sheetsPerCopy === 1 ? "" : "s"} × ${copies} cop${copies === 1 ? "y" : "ies"}${sidesSelect.value === "front_back" ? ` (${fileCount} file${fileCount === 1 ? "" : "s"}, front and back)` : ` (${fileCount} file${fileCount === 1 ? "" : "s"})`} × ₹${(sheetRate / 100).toFixed(2)}. Delivery, if selected, is added once to the order.`;
      addCartItemButton.disabled = cart.length >= 50;
      submitButton.disabled = cart.length === 0;
      updateCart();
    };

    categoryInputs.forEach((input) => input.addEventListener("change", updateOrderForm));
    deliveryInputs.forEach((input) => input.addEventListener("change", updateOrderForm));
    deliveryAddressChoice.addEventListener("change", updateOrderForm);
    orderForm.addEventListener("files-updated", updateOrderForm);
    orderForm.addEventListener("cart-updated", updateOrderForm);
    addCartItemButton.addEventListener("click", addItemToCart);
    orderForm.addEventListener("submit", (event) => {
      if (selectedFiles.length) {
        const itemData = buildCurrentItemData();
        if (!itemData) {
          event.preventDefault();
          orderHelp.textContent = cart.length >= 50
            ? "Your cart has reached the 50-item limit."
            : "Check the current item’s files, quantity, print settings, and any required notes.";
          return;
        }
        orderForm.append(createCartPayload(itemData, cart.length));
        cartCountInput.value = String(cart.length + 1);
      }
      if (cart.length === 0 && !selectedFiles.length) {
        event.preventDefault();
        return;
      }
      submitButton.disabled = true;
      submitButton.setAttribute("aria-busy", "true");
      orderForm.querySelector("[data-order-label]").textContent = "Placing order…";
    });
    [quantity, sizeSelect, modeSelect, sidesSelect].forEach((input) => input.addEventListener("input", updateOrderForm));
    [sizeSelect, modeSelect, sidesSelect, cadSize].forEach((input) => input.addEventListener("change", updateOrderForm));
    notes.addEventListener("input", updateOrderForm);
    updateOrderForm();
  }
});