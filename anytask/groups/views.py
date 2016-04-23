# Create your views here.
from django.shortcuts import render_to_response
from django.contrib.auth.decorators import login_required
from django.template import RequestContext

from groups.models import Group


def group_page(request):
    #group = Group.objects.filter(name=name)
    # context = {
    #     'group': group,
    # }
    return render_to_response('group_page.html')


def statistics(request):
    return render_to_response('statistics.html')

def queue(request):
    groups_list = Group.objects.all().order_by('name')

    #Make refferences in html file.
    context = {
        'groups_list': groups_list,
    }

    return render_to_response('queue.html', context, context_instance=RequestContext(request))