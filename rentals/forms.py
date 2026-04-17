from django import forms
from .models import Unit


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = [
            'number', 'unit_type', 'floor_level', 
            'monthly_rent', 'status', 'description', 'amenities'
        ]
        widgets = {
            'number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 101, A-201'
            }),
            'unit_type': forms.Select(attrs={
                'class': 'form-control'
            }),
            'floor_level': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '50'
            }),
            'monthly_rent': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '1000'
            }),
            'status': forms.Select(attrs={
                'class': 'form-control'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': '3',
                'placeholder': 'Describe the unit features, location, etc.'
            }),
            'amenities': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': '2',
                'placeholder': 'e.g., Air Conditioning, WiFi, Parking, Swimming Pool'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': field.widget.attrs.get('class', '') + ' tenant-form-input'})
            if field.required:
                field.widget.attrs.update({'required': 'required'})

    def clean_number(self):
        number = self.cleaned_data.get('number')
        if number:
            number = number.upper().strip()
            
            # Check for duplicate number, but exclude current instance if editing
            if self.instance and self.instance.pk:
                # We're editing an existing unit, exclude current instance from check
                if Unit.objects.exclude(pk=self.instance.pk).filter(number=number).exists():
                    raise forms.ValidationError(f'Unit with number {number} already exists.')
            else:
                # We're creating a new unit, check all units
                if Unit.objects.filter(number=number).exists():
                    raise forms.ValidationError(f'Unit with number {number} already exists.')
            
            return number
        return number

    def clean_monthly_rent(self):
        rent = self.cleaned_data.get('monthly_rent')
        if rent and rent < 1000:
            raise forms.ValidationError('Monthly rent must be at least ₱1,000')
        return rent

    
    def clean_amenities(self):
        amenities = self.cleaned_data.get('amenities')
        if amenities:
            # Clean up the amenities string
            amenities_list = [item.strip() for item in amenities.split(',') if item.strip()]
            return ', '.join(amenities_list)
        return amenities
