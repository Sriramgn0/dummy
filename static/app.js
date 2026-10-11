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

  const orderPopup = document.querySelector("[data-order-popup]");
  if (orderPopup) {
    const closeButtons = orderPopup.querySelectorAll("[data-popup-close]");
    const dismissPopup = () => orderPopup.remove();
    closeButtons.forEach((button) => button.addEventListener("click", dismissPopup));
    orderPopup.addEventListener("click", (event) => {
      if (event.target === orderPopup) dismissPopup();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") dismissPopup();
    }, { once: true });
    closeButtons[0]?.focus();
  }

  const fileInput = document.querySelector("#documents");
  const fileLabel = document.querySelector("[data-file-name]");
  const fileList = document.querySelector("[data-file-list]");
  let selectedFiles = [];

  if (fileInput && fileLabel) {
    const renderSelectedFiles = () => {
      const transfer = new DataTransfer();
      selectedFiles.forEach((file) => transfer.items.add(file));
      fileInput.files = transfer.files;
      fileLabel.textContent = selectedFiles.length
        ? `${selectedFiles.length} file${selectedFiles.length === 1 ? "" : "s"} selected — add more`
        : "Choose documents";
      fileList.replaceChildren();
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
        fileList.append(item);
      });
      fileList.hidden = selectedFiles.length === 0;
      fileInput.closest(".upload-zone")?.classList.toggle("has-file", selectedFiles.length > 0);
      fileInput.required = selectedFiles.length === 0;
    };

    fileInput.addEventListener("change", () => {
      Array.from(fileInput.files).forEach((file) => {
        const alreadySelected = selectedFiles.some((selected) =>
          selected.name === file.name &&
          selected.size === file.size &&
          selected.lastModified === file.lastModified
        );
        if (!alreadySelected) selectedFiles.push(file);
      });
      renderSelectedFiles();
      orderForm?.dispatchEvent(new Event("files-updated"));
    });
  }

  const orderForm = document.querySelector("[data-order-form]");
  if (orderForm) {
    const priceData = JSON.parse(document.querySelector("#digital-price-data")?.textContent || "{}");
    const categoryInputs = orderForm.querySelectorAll("[name='product_category']");
    const deliveryInputs = orderForm.querySelectorAll("[name='delivery_type']");
    const digitalFields = orderForm.querySelectorAll("[data-digital-field]");
    const cadField = orderForm.querySelector("[data-cad-field]");
    const cadSize = orderForm.querySelector("#cad_size");
    const deliveryAddressField = orderForm.querySelector("[data-delivery-address]");
    const deliveryAddress = orderForm.querySelector("#delivery_address");
    const notes = orderForm.querySelector("[data-order-notes]");
    const notesLabel = orderForm.querySelector("[data-notes-label]");
    const notesOptional = notesLabel.querySelector(".optional");
    const notesHint = orderForm.querySelector("[data-notes-hint]");
    const pricePreview = orderForm.querySelector("[data-price-preview]");
    const priceTotal = orderForm.querySelector("[data-price-total]");
    const priceUnit = orderForm.querySelector("[data-price-unit]");
    const priceHint = orderForm.querySelector("[data-price-hint]");
    const orderHelp = orderForm.querySelector("[data-order-help]");
    const orderLabel = orderForm.querySelector("[data-order-label]");
    const submitButton = orderForm.querySelector("[data-order-submit]");
    const quantity = orderForm.querySelector("[data-price-qty]");
    const sizeSelect = orderForm.querySelector("[data-price-size]");
    const modeSelect = orderForm.querySelector("[data-price-mode]");

    const updateOrderForm = () => {
      const category = orderForm.querySelector("[name='product_category']:checked")?.value;
      const isDigital = category === "digital_printing";
      const deliveryType = orderForm.querySelector("[name='delivery_type']:checked")?.value;
      const isDelivery = deliveryType === "delivery";
      const isCustomCad = !isDigital && cadSize.value === "Custom";
      digitalFields.forEach((field) => {
        field.hidden = !isDigital;
        field.querySelector("select").disabled = !isDigital;
      });
      cadField.hidden = isDigital;
      cadSize.disabled = isDigital;
      deliveryAddressField.hidden = !isDelivery;
      deliveryAddress.disabled = !isDelivery;
      deliveryAddress.required = isDelivery;
      notes.required = isCustomCad;
      notesHint.hidden = !isCustomCad;
      notesOptional.hidden = isCustomCad;
      notesLabel.firstChild.textContent = isCustomCad ? "Extra notes (required) " : "Anything we should know ";
      pricePreview.hidden = !isDigital;

      if (!isDigital) {
        orderHelp.textContent = isDelivery
          ? "CAD delivery charges will be included in the quotation."
          : "CAD orders are quoted by the print desk.";
        orderLabel.textContent = "Send CAD for a quote";
        submitButton.disabled = false;
        return;
      }

      orderHelp.textContent = "Estimate = files × prints per file × configured rate.";
      orderLabel.textContent = "Continue to payment";
      const sheetRate = priceData[sizeSelect.value]?.[modeSelect.value];
      const sheetCount = Number(quantity.value);
      const fileCount = selectedFiles.length;
      if (!sheetRate || !Number.isInteger(sheetCount) || sheetCount < 1 || fileCount < 1) {
        priceTotal.textContent = "Rate not set";
        priceUnit.textContent = "";
        priceHint.textContent = fileCount < 1
          ? "Select at least one file to see the estimate."
          : "The print desk needs to configure this size and print mode.";
        submitButton.disabled = true;
        return;
      }

      const deliveryFee = isDelivery ? Number(priceData.delivery_fee_paise || 0) : 0;
      const total = sheetRate * sheetCount * fileCount + deliveryFee;
      priceTotal.textContent = `₹${(total / 100).toFixed(2)}`;
      priceUnit.textContent = `₹${(sheetRate / 100).toFixed(2)} per print`;
      priceHint.textContent = `${fileCount} file${fileCount === 1 ? "" : "s"} × ${sheetCount} print${sheetCount === 1 ? "" : "s"} × ₹${(sheetRate / 100).toFixed(2)}${deliveryFee ? ` + ₹${(deliveryFee / 100).toFixed(2)} delivery` : ""}`;
      submitButton.disabled = false;
    };

    categoryInputs.forEach((input) => input.addEventListener("change", updateOrderForm));
    deliveryInputs.forEach((input) => input.addEventListener("change", updateOrderForm));
    orderForm.addEventListener("files-updated", updateOrderForm);
    [quantity, sizeSelect, modeSelect].forEach((input) => input.addEventListener("input", updateOrderForm));
    [sizeSelect, modeSelect, cadSize].forEach((input) => input.addEventListener("change", updateOrderForm));
    updateOrderForm();
  }
});