from django import forms


class ContactForm(forms.Form):
    ROLE_CHOICES = [('buyer', 'Buyer'), ('vendor', 'Vendor'), ('other', 'Other')]
    SUBJECT_CHOICES = [
        ('vendor_application', 'Vendor application'),
        ('report_problem', 'Report a problem'),
        ('general', 'General question'),
    ]

    role = forms.ChoiceField(choices=ROLE_CHOICES)
    name = forms.CharField(max_length=150)
    email = forms.EmailField()
    subject = forms.ChoiceField(choices=SUBJECT_CHOICES)
    message = forms.CharField(widget=forms.Textarea)


class ProductReportForm(forms.Form):
    REASON_CHOICES = [
        ('counterfeit', 'Counterfeit / fake item'),
        ('prohibited', 'Prohibited or illegal item'),
        ('misleading', 'Misleading listing or description'),
        ('other', 'Other'),
    ]

    reason = forms.ChoiceField(choices=REASON_CHOICES, label='Reason for reporting')
    details = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Provide any additional details (optional)'}),
        label='Additional details'
    )
