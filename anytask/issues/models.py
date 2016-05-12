# coding: utf-8

from datetime import datetime
import os
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.db import models
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import ugettext as _
from django.conf import settings
from issues.model_issue_field import IssueField
from decimal import Decimal
from anyrb.common import AnyRB
from anyrb.common import update_status_review_request
from anycontest.common import upload_contest
from tasks.models import Task

from unidecode import unidecode

import uuid
import requests

from markdown import markdown

def get_file_path(instance, filename):
    return '/'.join(['files', str(uuid.uuid4()), filename])


def normalize_decimal(number):
    new_number = Decimal(str(number))
    new_number = new_number.normalize()
    exponent = new_number.as_tuple()[2]
    if exponent > 10:
        new_number = Decimal(0)
    elif exponent > 0:
        new_number = new_number.quantize(1)

    return new_number


class File(models.Model):
    file = models.FileField(upload_to=get_file_path, null=True, blank=True, max_length = 500)
    event = models.ForeignKey('Event')
    deleted = models.BooleanField(default=False)

    def filename(self):
        return os.path.basename(self.file.name)


class Issue(models.Model):
    student = models.ForeignKey(User, db_index=True, null=False, blank=False, related_name='student')
    task = models.ForeignKey(Task, db_index=True, null=True, blank=False)

    create_time = models.DateTimeField(auto_now_add=True, default=datetime.now)
    update_time = models.DateTimeField(default=datetime.now)

    responsible = models.ForeignKey(User, db_index=True, null=True, blank=True, related_name='responsible')
    followers = models.ManyToManyField(User, null=True, blank=True)

    STATUS_NEW = 'new'
    STATUS_REWORK = 'rework'
    STATUS_VERIFICATION = 'verification'
    STATUS_ACCEPTED = 'accepted'
    STATUS_AUTO_VERIFICATION = 'auto_verification'
    STATUS_NEED_INFO = 'need_info'

    ISSUE_STATUSES = (
        (STATUS_NEW, _(u'Новый')),
        (STATUS_REWORK, _(u'На доработке')),
        (STATUS_VERIFICATION, _(u'На проверке')),
        (STATUS_ACCEPTED, _(u'Зачтено')),
        (STATUS_AUTO_VERIFICATION, _(u'На автоматической проверке')),
        (STATUS_NEED_INFO, _(u'Требуется информация')),
    )

    status = models.CharField(max_length=20, choices=ISSUE_STATUSES, default=STATUS_NEW)

    def score(self):
        field = get_object_or_404(IssueField, id=8)

        mark = self.get_field_value(field)
        if mark:
            mark = normalize_decimal(mark)
        else:
            mark = 0
        return mark

    def get_status(self):
        return dict(self.ISSUE_STATUSES)[self.status]

    def last_comment(self):
        field = get_object_or_404(IssueField, id=1)
        comment = self.get_field_value(field)
        if not comment:
            comment = ''

        return comment

    def get_field_repr(self, field):
        name = field.name

        def get_user_link(user):
            return u'<a class="user" href="{0}">{1} {2}</a>'.format(
                user.get_absolute_url(),
                user.last_name,
                user.first_name)

        if name == 'student_name':
            return get_user_link(self.student)
        if name == 'responsible_name':
            if self.responsible:
                return get_user_link(self.responsible)
            return None
        if name == 'followers_names':
            followers = map(lambda x: u'<a class="user" href="{0}">{1} {2}</a>'.format(x.get_absolute_url(), x.first_name, x.last_name),
                            self.followers.all())
            return ', '.join(followers)
        if name == 'course_name':
            course = self.task.course
            return u'<a href="{0}">{1}</a>'.format(course.get_absolute_url(), course.name)
        if name == 'task_name':
            task = self.task
            return task.title
        if name == 'comment':
            return None
        if name == 'status':
            return dict(self.ISSUE_STATUSES)[self.status]
        if name == 'mark':
            return self.score()
        if name == 'review_id' and self.task.course.rb_integrated:
            return u'<a href="{1}/r/{0}">{0}</a>'.format(
                self.get_byname('review_id'),
                settings.RB_API_URL,
            )
        if name == 'run_id' and self.task.course.contest_integrated:
            return u'<a href="https://contest.yandex.ru/contest/{1}/run-report/{0}">{0}</a>'.format(
                self.get_byname('run_id'),
                self.task.contest_id,
            )

        return self.get_field_value(field)

    def get_byname(self, name):
        field = get_object_or_404(IssueField, name=name)
        return self.get_field_value(field)

    def get_field_value(self, field):
        name = field.name
        if name == 'student_name':
            return self.student
        if name == 'responsible_name':
            if self.responsible:
                return self.responsible
            return None
        if name == 'followers_names':
            ret = []
            for user in self.followers.all():
                ret.append(user.id)
            return ret
        if name == 'course_name':
            return self.task.course
        if name == 'task_name':
            return self.task
        if name == 'status':
            return self.status
        if name == 'max_mark':
            return self.task.score_max

        events = Event.objects.filter(issue_id=self.id, field_id=field.id).order_by('-timestamp')[:1]
        if not events:
            fields_count = self.task.course.issue_fields.filter(id=field.id).count()
            if fields_count:
                self.set_field(field, field.get_default_value())
                if field.get_default_value() is not None:
                    return field.get_default_value()
                return ''
            else:
               raise AttributeError('field_name = {0}'.format(name))

        return events[0].value

    def get_field_value_for_form(self, field):
        ret = self.get_field_value(field)
        if field.name == 'responsible_name':
            if ret:
                ret = ret.id #Hack hack hack :\
            return ret
        return ret

    def create_event(self, field, author):
        event = Event()
        event.issue = self
        event.field = field
        event.author = author
        event.save()

        return event

    def set_byname(self, name, value, author=None):
        field = get_object_or_404(IssueField, name=name)
        return self.set_field(field, value, author)

    def set_field(self, field, value, author=None):
        event = self.create_event(field, author)
        name = field.name

        if name == 'responsible_name':
            new_responsible = value

            if self.responsible != new_responsible:
                new_followers = list(self.followers.all().exclude(id=new_responsible.id))
                if self.responsible:
                    new_followers.append(self.responsible)
                self.responsible = new_responsible
                self.followers = new_followers

            value = value.last_name + ' ' + value.first_name

        elif name == 'followers_names':
            if self.responsible and str(self.responsible.id) in value:
                value.remove(str(self.responsible.id))
            self.followers = list(value)

            value = []
            for follower in self.followers.all():
                value.append(follower.last_name + ' ' + follower.first_name)

            value = ', '.join(value)

        elif name == 'comment':
            if value:
                sent = True
                for file in value['files']:
                    file.name = unidecode(file.name)
                    uploaded_file = File(file=file, event=event)
                    uploaded_file.save()
                    if self.task.course.contest_integrated:
                        for ext in settings.CONTEST_EXTENSIONS:
                            filename, extension = os.path.splitext(file.name)
                            if ext == extension:
                                sent, message = upload_contest(event, ext, uploaded_file)
                                if sent:
                                    value['comment'] += u"Отправлено на проверку в Я.Контест"
                                    if self.status != self.STATUS_ACCEPTED:
                                        self.set_byname('status', self.STATUS_AUTO_VERIFICATION)
                                else:
                                    value['comment'] += u"Ошибка отправки в Я.Контест ('{0}').".format(message)
                                    self.followers.add(User.objects.get(username='anytask'))
                                break

                    if self.task.course.rb_integrated and (self.task.course.send_rb_and_contest_together or not self.task.course.contest_integrated):
                        for ext in settings.RB_EXTENSIONS:
                            filename, extension = os.path.splitext(file.name)
                            if ext == extension:
                                anyrb = AnyRB(event)
                                review_request_id = anyrb.upload_review()
                                if review_request_id is not None:
                                    value['comment'] += '\n' + \
                                              u'<a href="{1}/r/{0}">Review request {0}</a>'. \
                                              format(review_request_id,settings.RB_API_URL)
                                else:
                                    value['comment'] += '\n' + u'Ошибка отправки в Review Board.'
                                break

                if self.status != self.STATUS_AUTO_VERIFICATION and self.status != self.STATUS_ACCEPTED:
                    if author == self.student and self.status != self.STATUS_NEED_INFO and sent:
                        self.set_byname('status', self.STATUS_VERIFICATION)
                    if author == self.responsible:
                        self.status = self.STATUS_REWORK
                if not value['files'] and not value['comment']:
                    event.delete()
                    return
                else:
                    self.update_time = datetime.now()
                    value = value['comment']

        elif name == 'status':
            try:
                review_id = self.get_byname('review_id')
                if review_id != '':
                    if value == self.STATUS_ACCEPTED:
                        update_status_review_request(review_id,'submitted')
                    elif self.status == self.STATUS_ACCEPTED:
                        update_status_review_request(review_id,'pending')
            except:
                pass

            self.status = value
            value = self.get_status()

        elif name == 'mark':
            if not value:
                value = 0
            value = normalize_decimal(value)
            value = str(value)
            if self.status != self.STATUS_ACCEPTED and self.status != self.STATUS_NEW:
                self.set_byname('status', 'rework')

        self.save()

        if not value:
            value = ''

        course = self.task.course
        group = course.get_user_group(self.student)
        default_teacher = course.get_default_teacher(group)
        if default_teacher and (not self.get_byname('responsible_name')):
            self.set_byname('responsible_name', default_teacher)

        event.value = value
        event.save()
        event.pull_plugins()


        pass

    def get_history(self):
        """
        :returns event objects
        """
        events = Event.objects.filter(issue_id=self.id).exclude(Q(author__isnull=True) |
                    Q(field__name='review_id')).order_by('timestamp')
        return events

    def __unicode__(self):
        return u'Issue: {0} {1}'.format(self.id, self.task.title)

    def get_absolute_url(self):
        return reverse('issues.views.issue_page', args=[str(self.id)])


class Event(models.Model):
    issue = models.ForeignKey(Issue, null=False, blank=False)
    author = models.ForeignKey(User, db_index=True, null=True, blank=True)
    field = models.ForeignKey(IssueField, blank=False, default=1)

    value = models.TextField(max_length=2500, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    sended_notify = models.BooleanField(default=False)

    def pull_plugins(self):
        # upload_review(self)
        # from anycontest.common import AnyContest
        # AnyContest(self)
        pass

    def get_message(self):
        message = list()
        if self.field.history_message:
            message.append(self.field.history_message)
        message.append(self.value)

        messageWithMarkdown = list()
        for eachMessage in message:
            messageToAppend = eachMessage.replace("\\\\", "latex2slashes")
            messageToAppend = markdown(messageToAppend)
            messageToAppend = messageToAppend.replace("latex2slashes", "\\\\")

            messageWithMarkdown.append(messageToAppend)
        return ' '.join(messageWithMarkdown)

    def get_notify_message(self):
        message = list()
        timestamp = self.timestamp.strftime('%d %b %H:%M')
        message.append(timestamp.decode('utf-8'))
        message.append(u'{0} {1}:'.format(self.author.last_name, self.author.first_name))
        message.append(self.get_message())
        if self.file_set.all():
            file_list = list()
            for file in self.file_set.all():
                file_list.append(file.filename())
            message.append(', '.join(file_list))
        return u'\n'.join(message)

    def is_comment(self):
        return self.field.name == 'comment'

    def is_change(self):
        return self.field.name != 'comment'

#    def save(self, *a, **ka):
#        import traceback
#        traceback.print_stack()
#        return super(self.__class__, self).save(*a, **ka)

    def __unicode__(self):
        if not self.author:
            ret = u'{0} nobody'.format(self.issue.id)
        else:
            ret = u'{1} {0}'.format(self.author.first_name,
                                    self.issue.id)
        if self.is_change():
            ret += u' {0}'.format(self.field.name)
        return ret
