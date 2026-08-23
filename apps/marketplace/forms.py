from django import forms


class ContactForm(forms.Form):
    ROLE_CHOICES = [('buyer', 'Buyer'), ('vendor', 'Vendor'), ('other', 'Other')]
    SUBJECT_CHOICES = [
        ('order_issue', 'Order issue'),
        ('vendor_application', 'Vendor application'),
        ('report_problem', 'Report a problem'),
        ('general', 'General question'),
    ]

    role = forms.ChoiceField(choices=ROLE_CHOICES)
    name = forms.CharField(max_length=150)
    email = forms.EmailField()
    subject = forms.ChoiceField(choices=SUBJECT_CHOICES)
    message = forms.CharField(widget=forms.Textarea)
