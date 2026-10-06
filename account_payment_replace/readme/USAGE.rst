#. Open a **posted** customer or vendor payment that is reconciled with
   invoice(s) / bill(s) and **not** matched with a bank statement.

   Or open the **paid/partial invoice** itself.
#. Click **Edit Payment** or **Replace Payment** (form header), depending on
   the company setting, or use *Action → Modify Payment*.
#. The standard **Register Payment** wizard opens, prefilled with journal,
   date, amount, method, memo and simple write-off when applicable.

Replace mode
============

#. The payment is cancelled (after automatic unreconcile).
#. Adjust only what is wrong and confirm.
#. Both payments stay linked:

   * original → *Replacement Payment*
   * new → *Replaced Payment*

   Chatter messages document the replacement on both records.

Edit mode
=========

#. The payment is reset to draft (not cancelled).
#. Adjust only what is wrong and confirm.
#. The same payment record is re-posted.
#. A chatter message lists the changed fields (old → new values).

If you close the wizard without confirming in edit mode, the payment remains
in draft and must be posted or cancelled manually.

If the invoice has several payments, the action opens the payment list so you
can open one and modify it.
