from django.conf.urls import patterns, url

from filemanager import path_end

urlpatterns = patterns('groups.views',
    url(r'^$', 'queue'),
    url(r'^group_page$', 'group_page'),
    url(r'^statistics$', 'statistics'),

)
