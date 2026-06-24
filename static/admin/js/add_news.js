document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const tabButtons = document.querySelectorAll(".tab-btn");
    const tabPanels = document.querySelectorAll(".tab-panel");
    const intakeForm = document.getElementById("intake-form");
    const urlInput = document.getElementById("url-input");
    const textInput = document.getElementById("text-input");
    const extractBtn = document.getElementById("extract-btn");
    const loadingDiv = document.getElementById("loading");
    const errorAlert = document.getElementById("error-alert");
    const errorMessage = document.getElementById("error-message");
    const successAlert = document.getElementById("success-alert");
    const successMessage = document.getElementById("success-message");
    const previewCard = document.getElementById("preview-card");
    
    // Preview Card Elements
    const previewTitle = document.getElementById("preview-title");
    const previewAuthor = document.getElementById("preview-author");
    const previewDate = document.getElementById("preview-date");
    const previewSummaryText = document.getElementById("preview-summary-text");
    const previewTagChips = document.getElementById("preview-tag-chips");
    const publishBtn = document.getElementById("publish-btn");

    // Dialog Elements
    const dialog = document.getElementById("missing-fields-dialog");
    const dialogForm = document.getElementById("dialog-form");
    const dynamicInputs = document.getElementById("dynamic-inputs");
    const closeDialogBtn = document.getElementById("close-dialog-btn");

    let currentExtraction = null;
    let activeTab = "url";

    // CSRF Token
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";

    // 1. Tab Switching logic
    tabButtons.forEach(button => {
        button.addEventListener("click", () => {
            tabButtons.forEach(btn => btn.classList.remove("active"));
            tabPanels.forEach(panel => panel.classList.remove("active"));

            button.classList.add("active");
            activeTab = button.dataset.tab;

            const targetPanel = document.getElementById(`panel-${activeTab}`);
            if (targetPanel) {
                targetPanel.classList.add("active");
            }

            // Manage required fields
            if (activeTab === "url") {
                urlInput.setAttribute("required", "required");
                textInput.removeAttribute("required");
            } else {
                textInput.setAttribute("required", "required");
                urlInput.removeAttribute("required");
            }
        });
    });

    // 2. Submit Intake Form for extraction
    intakeForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        // Reset display states
        errorAlert.style.display = "none";
        successAlert.style.display = "none";
        previewCard.style.display = "none";
        
        const content = activeTab === "url" ? urlInput.value : textInput.value;
        if (!content || !content.trim()) {
            showError("Content is required.");
            return;
        }

        // Set Loading State
        loadingDiv.style.display = "flex";
        extractBtn.disabled = true;

        try {
            const response = await fetch("/admin/extract-preview/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken
                },
                body: JSON.stringify({
                    mode: activeTab,
                    content: content
                })
            });

            const data = await response.json();

            if (!response.ok) {
                showError(data.detail || "Failed to extract metadata.");
                return;
            }

            handleExtractionResult(data);
        } catch (err) {
            showError("Network error occurred while calling the AI service.");
            console.error(err);
        } finally {
            loadingDiv.style.display = "none";
            extractBtn.disabled = false;
        }
    });

    // 3. Handle Extraction Result
    function handleExtractionResult(data) {
        if (!data.is_valid_news) {
            showError(data.summary || "This content does not appear to be tech or AI-related news.");
            return;
        }

        currentExtraction = data;

        // Check if there are missing fields
        // Filters missing fields to keep only core attributes (excluding tags from simple text input checks)
        const coreMissing = data.missing_fields.filter(field => field !== "tags");

        if (coreMissing.length > 0 || data.missing_fields.includes("tags")) {
            showMissingFieldsDialog(data, coreMissing);
        } else {
            showPreviewCard(data);
        }
    }

    // 4. Render and Open Modal Dialog
    function showMissingFieldsDialog(data, coreMissing) {
        dynamicInputs.innerHTML = "";

        // Dynamically add input fields for core missing attributes
        coreMissing.forEach(field => {
            const group = document.createElement("div");
            group.className = "form-group";

            const label = document.createElement("label");
            label.textContent = capitalizeFirstLetter(field.replace("_", " "));
            label.setAttribute("for", `dialog-input-${field}`);

            let input;
            if (field === "summary") {
                input = document.createElement("textarea");
                input.rows = 3;
            } else {
                input = document.createElement("input");
                input.type = "text";
                if (field === "published_at") {
                    input.placeholder = "YYYY-MM-DDTHH:MM:SSZ (ISO 8601)";
                }
            }
            input.id = `dialog-input-${field}`;
            input.name = field;
            input.setAttribute("required", "required");

            group.appendChild(label);
            group.appendChild(input);
            dynamicInputs.appendChild(group);
        });

        // Set tag checkboxes matching current extraction tags
        const tagCheckboxes = dialogForm.querySelectorAll('input[name="dialog-tags"]');
        tagCheckboxes.forEach(cb => {
            cb.checked = data.tags.includes(cb.value);
        });

        // Show standard modal popup instantly (utilitarian/snappy motion perSTYLE.md)
        dialog.showModal();
    }

    // 5. Render Clean Preview Card
    function showPreviewCard(data) {
        previewTitle.textContent = data.title;
        previewAuthor.textContent = data.author || "Unknown";
        previewDate.textContent = formatDate(data.published_at);
        previewSummaryText.textContent = data.summary;

        // Render chips
        previewTagChips.innerHTML = "";
        data.tags.forEach(tag => {
            const chip = document.createElement("span");
            chip.className = "chip";
            chip.textContent = tag;
            previewTagChips.appendChild(chip);
        });

        previewCard.style.display = "block";
    }

    // 6. Dialog close/cancel
    closeDialogBtn.addEventListener("click", () => {
        dialog.close();
    });

    // 7. Dialog form submit (Confirm & Publish)
    dialogForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        // Gather tags
        const selectedTags = [];
        const checkedBoxes = dialogForm.querySelectorAll('input[name="dialog-tags"]:checked');
        checkedBoxes.forEach(cb => {
            selectedTags.push(cb.value);
        });

        if (selectedTags.length === 0) {
            alert("At least one tag is required.");
            return;
        }

        // Construct final metadata payload
        const payload = {
            title: getDialogInputValue("title", currentExtraction.title),
            author: getDialogInputValue("author", currentExtraction.author),
            published_at: getDialogInputValue("published_at", currentExtraction.published_at),
            summary: getDialogInputValue("summary", currentExtraction.summary),
            tags: selectedTags,
            original_url: activeTab === "url" ? urlInput.value : null,
            raw_input: currentExtraction.raw_input
        };

        await submitPublish(payload);
    });

    // 8. Publish from Clean Preview Card (Direct Publish)
    publishBtn.addEventListener("click", async () => {
        const payload = {
            title: currentExtraction.title,
            author: currentExtraction.author,
            published_at: currentExtraction.published_at,
            summary: currentExtraction.summary,
            tags: currentExtraction.tags,
            original_url: activeTab === "url" ? urlInput.value : null,
            raw_input: currentExtraction.raw_input
        };

        await submitPublish(payload);
    });

    // 9. Send publish payload to backend
    async function submitPublish(payload) {
        // Clear alerts
        errorAlert.style.display = "none";
        successAlert.style.display = "none";

        try {
            const response = await fetch("/admin/publish/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken
                },
                body: JSON.stringify(payload)
            });

            const data = await response.json();

            if (response.status === 201) {
                // Success
                if (dialog.open) dialog.close();
                previewCard.style.display = "none";
                
                successMessage.innerHTML = `Article published successfully! <a href="/admin/posts/post/${data.post_id}/change/" class="alert-link">Edit post #${data.post_id}</a>`;
                successAlert.style.display = "block";
                
                // Reset main form
                intakeForm.reset();
            } else if (response.status === 409) {
                // Duplicate URL hash conflict
                if (dialog.open) dialog.close();
                errorMessage.innerHTML = `A post with this URL already exists: <a href="/admin/posts/post/${data.post_id}/change/" class="alert-link">view post #${data.post_id}</a>`;
                errorAlert.style.display = "block";
            } else {
                // Validation error or bad request
                errorMessage.textContent = data.detail || "Failed to publish post.";
                errorAlert.style.display = "block";
            }
        } catch (err) {
            errorMessage.textContent = "Network error while publishing.";
            errorAlert.style.display = "block";
            console.error(err);
        }
    }

    // Helper functions
    function showError(msg) {
        errorMessage.textContent = msg;
        errorAlert.style.display = "block";
    }

    function capitalizeFirstLetter(string) {
        return string.charAt(0).toUpperCase() + string.slice(1);
    }

    function getDialogInputValue(fieldName, fallbackValue) {
        const input = document.getElementById(`dialog-input-${fieldName}`);
        return input ? input.value : fallbackValue;
    }

    function formatDate(isoString) {
        if (!isoString) return "Not specified";
        try {
            const date = new Date(isoString);
            if (isNaN(date.getTime())) return isoString;
            return date.toLocaleString();
        } catch (e) {
            return isoString;
        }
    }
});
