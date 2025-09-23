from django import forms
from django.core.exceptions import ValidationError
from .models import Survey, Question, Choice, Response, Answer


class SurveyResponseForm(forms.Form):
    """
    Dynamic form for survey responses - built dynamically based on survey questions
    """

    def __init__(self, survey, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.survey = survey
        self.questions = survey.questions.prefetch_related('choices').order_by('order')

        # Create form fields dynamically based on questions
        for question in self.questions:
            field_name = f'question_{question.id}'

            if question.question_type == 'mcq':
                # Multiple choice field
                choices = [(choice.id, choice.choice_text) for choice in question.choices.order_by('order')]
                self.fields[field_name] = forms.ChoiceField(
                    label=question.question_text,
                    choices=[('', 'Select an option')] + choices,
                    required=question.is_required,
                    widget=forms.RadioSelect(attrs={'class': 'form-radio'})
                )

            elif question.question_type == 'text':
                # Text field
                self.fields[field_name] = forms.CharField(
                    label=question.question_text,
                    required=question.is_required,
                    widget=forms.Textarea(attrs={
                        'class': 'form-textarea',
                        'rows': 3,
                        'placeholder': 'Enter your answer...'
                    })
                )

            elif question.question_type == 'rating':
                # Rating scale field
                rating_choices = [
                    (i, str(i)) for i in range(question.rating_min, question.rating_max + 1)
                ]
                self.fields[field_name] = forms.ChoiceField(
                    label=question.question_text,
                    choices=[('', 'Select rating')] + rating_choices,
                    required=question.is_required,
                    widget=forms.RadioSelect(attrs={'class': 'form-radio rating-scale'})
                )

            elif question.question_type == 'boolean':
                # Yes/No field
                self.fields[field_name] = forms.ChoiceField(
                    label=question.question_text,
                    choices=[('', 'Select answer'), ('true', 'Yes'), ('false', 'No')],
                    required=question.is_required,
                    widget=forms.RadioSelect(attrs={'class': 'form-radio'})
                )