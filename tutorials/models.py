# tutorials/models.py
import uuid
import os
from django.db import models, migrations
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator
from django.urls import reverse

User = get_user_model()


def tutorial_video_upload_path(instance, filename):
    """Generate upload path for tutorial videos"""
    # Create path: tutorials/videos/tutorial_id/filename
    return f'tutorials/videos/{instance.id}/{filename}'


class TutorialCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True, help_text="Font Awesome icon class (e.g., fas fa-video)")
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Tutorial Categories"
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def get_tutorial_count(self):
        return self.tutorials.filter(is_published=True).count()


class Tutorial(models.Model):
    VIDEO_SOURCE_CHOICES = [
        ('url', 'External URL'),
        ('upload', 'Uploaded File'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField()
    category = models.ForeignKey(
        TutorialCategory,
        on_delete=models.CASCADE,
        null=True,  # Add this
        blank=True,  # Add this
        related_name='tutorials',
        help_text="Optional category for organizing tutorials"
    )
    # Video configuration - UPDATED
    video_source = models.CharField(
        max_length=10,
        choices=VIDEO_SOURCE_CHOICES,
        default='url',
        help_text="Source of the video content"
    )
    video_url = models.URLField(blank=True, null=True, help_text="YouTube, Vimeo, or direct video URL")
    video_file = models.FileField(
        upload_to=tutorial_video_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=['mp4', 'webm', 'avi', 'mov', 'mkv'])],
        blank=True,
        null=True,
        help_text="Upload video file (MP4, WebM, AVI, MOV, MKV - Max 500MB)"
    )
    video_duration = models.DurationField(help_text="Video duration (automatically detected if possible)")
    thumbnail = models.ImageField(upload_to='tutorial_thumbnails/', blank=True, null=True)

    # Tutorial ordering and prerequisites
    order = models.PositiveIntegerField(default=0)
    prerequisites = models.ManyToManyField('self', blank=True, symmetrical=False,
                                           help_text="Tutorials that must be completed before this one")

    # Quiz configuration - UPDATED field names to match your existing structure
    quiz_required = models.BooleanField(default=False, help_text="Require quiz completion for tutorial")
    quiz_passing_score = models.PositiveIntegerField(
        default=70,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Minimum percentage needed to pass the quiz"
    )
    max_quiz_attempts = models.PositiveIntegerField(default=3, help_text="Maximum quiz attempts allowed")

    # Rewards
    completion_reward = models.DecimalField(max_digits=10, decimal_places=2, default=0.00,
                                            help_text="Reward amount for completing tutorial")

    # Status
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'order', 'title']
        unique_together = ['category', 'order']

    def __str__(self):
        return f"{self.category.name} - {self.title}"

    def get_absolute_url(self):
        return reverse('tutorials:tutorial_detail', kwargs={'pk': self.pk})

    def get_quiz_questions_count(self):
        return self.quiz_questions.count()

    def is_accessible_by_user(self, user):
        """Check if user can access this tutorial based on prerequisites"""
        if not self.prerequisites.exists():
            return True

        completed_tutorials = UserTutorialProgress.objects.filter(
            user=user, tutorial__in=self.prerequisites.all(), is_completed=True
        ).values_list('tutorial_id', flat=True)

        return set(completed_tutorials) >= set(self.prerequisites.values_list('id', flat=True))

    # NEW METHODS for video handling
    def get_video_url(self):
        """Return the appropriate video URL based on source"""
        if self.video_source == 'upload' and self.video_file:
            return self.video_file.url
        elif self.video_source == 'url' and self.video_url:
            return self.video_url
        return None

    def get_video_embed_url(self):
        """Return embed-friendly URL for external videos"""
        if self.video_source == 'url' and self.video_url:
            # YouTube
            if 'youtube.com' in self.video_url or 'youtu.be' in self.video_url:
                video_id = self.extract_youtube_id()
                if video_id:
                    return f"https://www.youtube.com/embed/{video_id}"
            # Vimeo
            elif 'vimeo.com' in self.video_url:
                video_id = self.video_url.split('/')[-1].split('?')[0]
                return f"https://player.vimeo.com/video/{video_id}"
        return self.get_video_url()

    def extract_youtube_id(self):
        """Extract YouTube video ID from various URL formats"""
        import re
        if not self.video_url:
            return None

        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, self.video_url)
            if match:
                return match.group(1)
        return None

    def clean(self):
        """Validate that either video_url or video_file is provided"""
        from django.core.exceptions import ValidationError

        if self.video_source == 'url' and not self.video_url:
            raise ValidationError("Video URL is required when using external URL source.")
        elif self.video_source == 'upload' and not self.video_file:
            raise ValidationError("Video file is required when using file upload source.")

    def delete(self, *args, **kwargs):
        """Delete associated video file when tutorial is deleted"""
        if self.video_file:
            # Delete the file from storage
            if os.path.isfile(self.video_file.path):
                os.remove(self.video_file.path)
        super().delete(*args, **kwargs)


class QuizQuestion(models.Model):
    QUESTION_TYPES = [
        ('multiple_choice', 'Multiple Choice'),
        ('true_false', 'True/False'),
        ('single_choice', 'Single Choice'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tutorial = models.ForeignKey(Tutorial, on_delete=models.CASCADE, related_name='quiz_questions')

    # UPDATED to match the view expectations
    question = models.TextField()  # Changed from question_text to question
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES, default='multiple_choice')
    order = models.PositiveIntegerField(default=0)
    points = models.PositiveIntegerField(default=1, help_text="Points awarded for correct answer")
    explanation = models.TextField(blank=True, help_text="Explanation shown after answering")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tutorial', 'order']
        unique_together = ['tutorial', 'order']

    def __str__(self):
        return f"{self.tutorial.title} - Q{self.order}: {self.question[:50]}..."


class QuizAnswer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE, related_name='answers')

    # UPDATED to match the view expectations
    answer = models.CharField(max_length=500)  # Changed from answer_text to answer
    is_correct = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['question', 'order']

    def __str__(self):
        return f"{self.question.question[:30]}... - {self.answer}"


class UserTutorialProgress(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tutorial_progress')
    tutorial = models.ForeignKey(Tutorial, on_delete=models.CASCADE, related_name='user_progress')

    # Video progress
    video_watch_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00,
                                                 validators=[MinValueValidator(0), MaxValueValidator(100)])
    video_completed_at = models.DateTimeField(null=True, blank=True)

    # Quiz progress - UPDATED field names to match view expectations
    quiz_attempts = models.PositiveIntegerField(default=0)
    score_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00,
                                           validators=[MinValueValidator(0),
                                                       MaxValueValidator(100)])  # Changed from best_quiz_score
    is_passed = models.BooleanField(default=False)  # Changed from quiz_passed
    quiz_completed_at = models.DateTimeField(null=True, blank=True)

    # Overall progress
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    reward_claimed = models.BooleanField(default=False)

    # Timestamps
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'tutorial']

    def __str__(self):
        return f"{self.user.username} - {self.tutorial.title} ({self.get_progress_percentage():.1f}%)"

    def get_progress_percentage(self):
        """Calculate overall progress percentage"""
        video_weight = 0.4  # 40% for watching video
        quiz_weight = 0.6  # 60% for passing quiz

        video_progress = min(self.video_watch_percentage, 100) * video_weight / 100
        quiz_progress = self.score_percentage * quiz_weight / 100 if self.is_passed else 0

        return (video_progress + quiz_progress) * 100

    def can_take_quiz(self):
        """Check if user can take the quiz"""
        return (self.video_watch_percentage >= 90 and
                self.quiz_attempts < self.tutorial.max_quiz_attempts)


class UserQuizAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='quiz_attempts')
    tutorial = models.ForeignKey(Tutorial, on_delete=models.CASCADE, related_name='quiz_attempts')
    attempt_number = models.PositiveIntegerField()

    # Results
    score_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00,
                                           validators=[MinValueValidator(0), MaxValueValidator(100)])
    total_questions = models.PositiveIntegerField()
    correct_answers = models.PositiveIntegerField()
    time_taken = models.DurationField(null=True, blank=True)

    # Status
    is_passed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'tutorial', 'attempt_number']
        ordering = ['-completed_at']

    def __str__(self):
        return f"{self.user.username} - {self.tutorial.title} - Attempt {self.attempt_number} ({self.score_percentage}%)"


class UserQuizAnswer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz_attempt = models.ForeignKey(UserQuizAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE)
    selected_answer = models.ForeignKey(QuizAnswer, on_delete=models.CASCADE)
    is_correct = models.BooleanField()
    answered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.quiz_attempt.user.username} - Q{self.question.order} - {'✓' if self.is_correct else '✗'}"


class Migration(migrations.Migration):
    dependencies = [
        ('tutorials', '0001_initial'),  # Replace with your actual last migration
    ]

    operations = [
        # Add new fields to UserTutorialProgress
        migrations.AddField(
            model_name='usertutorialprogress',
            name='last_watched_position',
            field=models.FloatField(default=0.0, help_text='Last playback position in seconds'),
        ),
        migrations.AddField(
            model_name='usertutorialprogress',
            name='preferred_playback_speed',
            field=models.FloatField(default=1.0, help_text="User's preferred playback speed"),
        ),
        migrations.AddField(
            model_name='usertutorialprogress',
            name='total_watch_time',
            field=models.FloatField(default=0.0, help_text='Total time spent watching this tutorial in seconds'),
        ),
        migrations.AddField(
            model_name='usertutorialprogress',
            name='resumed_count',
            field=models.IntegerField(default=0, help_text='Number of times user resumed watching'),
        ),

        # Create TutorialChapter model (optional)
        migrations.CreateModel(
            name='TutorialChapter',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(help_text='Chapter title', max_length=200)),
                ('description', models.TextField(blank=True, help_text='Chapter description')),
                ('start_time', models.FloatField(help_text='Start time in seconds')),
                ('end_time', models.FloatField(help_text='End time in seconds')),
                ('order', models.IntegerField(default=1)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('tutorial', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='chapters',
                                               to='tutorials.tutorial')),
            ],
            options={
                'ordering': ['tutorial', 'order'],
                'unique_together': {('tutorial', 'order')},
            },
        ),
    ]