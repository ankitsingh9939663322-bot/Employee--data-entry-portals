document.addEventListener("DOMContentLoaded", () => {

    console.log("Nexora Portal Loaded");

    const form = document.getElementById("task");

    /*
     * This JS is mainly for the employee workspace.
     * If the current page does not contain the task form,
     * simply stop here.
     */
    if (!form) {
        return;
    }


    const indexField = document.getElementById("idx");

    const employeeIndex = indexField
        ? indexField.value
        : "0";


    /*
     * Keep a separate draft for each record.
     * This means record #15's draft won't overwrite
     * record #16's draft.
     */
    const draftKey =
        "nexora_employee_draft_" + employeeIndex;


    const fields = [
        "name",
        "age",
        "city",
        "phone",
        "email"
    ];


    /*
     * -----------------------------------------------------
     * RESTORE SAVED DRAFT
     * -----------------------------------------------------
     */

    try {

        const saved =
            localStorage.getItem(draftKey);

        if (saved) {

            const data =
                JSON.parse(saved);

            fields.forEach((field) => {

                const input =
                    form.elements[field];

                if (
                    input &&
                    typeof data[field] === "string"
                ) {
                    input.value = data[field];
                }

            });

            console.log(
                "Saved draft restored for record:",
                employeeIndex
            );
        }

    } catch (error) {

        console.warn(
            "Could not restore draft:",
            error
        );

    }


    /*
     * -----------------------------------------------------
     * AUTO-SAVE WHILE TYPING
     * -----------------------------------------------------
     */

    function saveDraft() {

        const data = {};

        fields.forEach((field) => {

            const input =
                form.elements[field];

            if (input) {
                data[field] = input.value;
            }

        });


        try {

            localStorage.setItem(
                draftKey,
                JSON.stringify(data)
            );

        } catch (error) {

            console.warn(
                "Could not save draft:",
                error
            );

        }
    }


    /*
     * Save after every input change.
     */

    fields.forEach((field) => {

        const input =
            form.elements[field];

        if (!input) {
            return;
        }

        input.addEventListener(
            "input",
            saveDraft
        );

    });


    /*
     * -----------------------------------------------------
     * CLEAR DRAFT
     * -----------------------------------------------------
     *
     * Clear button should also remove the saved draft.
     */

    const resetButton =
        form.querySelector(
            'button[type="reset"]'
        );

    if (resetButton) {

        resetButton.addEventListener(
            "click",
            () => {

                try {

                    localStorage.removeItem(
                        draftKey
                    );

                } catch (error) {

                    console.warn(
                        "Could not clear draft:",
                        error
                    );

                }

            }
        );

    }


    /*
     * -----------------------------------------------------
     * PREVENT DOUBLE SUBMISSION
     * -----------------------------------------------------
     */

    let submitting = false;


    form.addEventListener(
        "submit",
        (event) => {

            if (submitting) {

                event.preventDefault();

                return;
            }


            submitting = true;


            const submitButton =
                form.querySelector(
                    'button[type="submit"]'
                );


            if (submitButton) {

                submitButton.disabled =
                    true;

                submitButton.textContent =
                    "Saving...";

            }


            /*
             * Successful submission means this
             * record is complete, so remove its draft.
             */

            try {

                localStorage.removeItem(
                    draftKey
                );

            } catch (error) {

                console.warn(
                    "Could not remove draft:",
                    error
                );

            }

        }
    );


    /*
     * -----------------------------------------------------
     * UNSAVED-CHANGE WARNING
     * -----------------------------------------------------
     */

    let hasChanges = false;


    fields.forEach((field) => {

        const input =
            form.elements[field];

        if (!input) {
            return;
        }

        input.addEventListener(
            "input",
            () => {
                hasChanges = true;
            }
        );

    });


    form.addEventListener(
        "submit",
        () => {
            hasChanges = false;
        }
    );


    window.addEventListener(
        "beforeunload",
        (event) => {

            if (!hasChanges || submitting) {
                return;
            }

            event.preventDefault();

            event.returnValue = "";
        }
    );

});
