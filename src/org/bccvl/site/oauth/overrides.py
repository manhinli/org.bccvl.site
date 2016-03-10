from Products.CMFCore.utils import getToolByName
from plone.app.users.browser.passwordpanel import PasswordPanel as BasePasswordPanel
from plone.app.users.browser.personalpreferences import PersonalPreferencesPanel as BasePersonalPreferencesPanel
from plone.app.users.browser.userdatapanel import UserDataPanel as BaseUserDataPanel
from zope.component import getMultiAdapter



class UserDataPanel(BaseUserDataPanel):
    # overriding it here to add additional tabs
    # -> rather monkey patch base class?

    def prepareObjectTabs(self,
                          default_tab='view',
                          sort_first=['folderContents']):

        tabs = super(UserDataPanel, self).prepareObjectTabs(default_tab, sort_first)
        navigation_root_url = self.context.absolute_url()
        mt = getToolByName(self.context, 'portal_membership')

        def _check_allowed(context, request, name):
            """Check, if user has required permissions on view.
            """
            view = getMultiAdapter((context, request), name=name)
            allowed = True
            for perm in view.__ac_permissions__:
                allowed = allowed and mt.checkPermission(perm[0], context)
            return allowed

        # TODO: insert before id:user_data-change-password
        if _check_allowed(self.context, self.request, 'oauth-preferences'):
            tabs.append({
                'title': u'User Sharing Settings',
                'url': navigation_root_url + '/@@oauth-preferences',
                'selected': (self.__name__ == 'oauth-preferences'),
                'id': 'user_data-oauth-preferences',
            })
        return tabs


class PasswordPanel(BasePasswordPanel):
    # overriding it here to add additional tabs
    # -> rather monkey patch base class?

    def prepareObjectTabs(self,
                          default_tab='view',
                          sort_first=['folderContents']):

        tabs = super(PasswordPanel, self).prepareObjectTabs(default_tab, sort_first)
        navigation_root_url = self.context.absolute_url()
        mt = getToolByName(self.context, 'portal_membership')

        def _check_allowed(context, request, name):
            """Check, if user has required permissions on view.
            """
            view = getMultiAdapter((context, request), name=name)
            allowed = True
            for perm in view.__ac_permissions__:
                allowed = allowed and mt.checkPermission(perm[0], context)
            return allowed

        # TODO: insert before id:user_data-change-password
        if _check_allowed(self.context, self.request, 'oauth-preferences'):
            tabs.append({
                'title': u'User Sharing Settings',
                'url': navigation_root_url + '/@@oauth-preferences',
                'selected': (self.__name__ == 'oauth-preferences'),
                'id': 'user_data-oauth-preferences',
            })
        return tabs


class PersonalPreferencesPanel(BasePersonalPreferencesPanel):
    # overriding it here to add additional tabs
    # -> rather monkey patch base class?

    def prepareObjectTabs(self,
                          default_tab='view',
                          sort_first=['folderContents']):

        tabs = super(PersonalPreferencesPanel, self).prepareObjectTabs(default_tab, sort_first)
        navigation_root_url = self.context.absolute_url()
        mt = getToolByName(self.context, 'portal_membership')

        def _check_allowed(context, request, name):
            """Check, if user has required permissions on view.
            """
            view = getMultiAdapter((context, request), name=name)
            allowed = True
            for perm in view.__ac_permissions__:
                allowed = allowed and mt.checkPermission(perm[0], context)
            return allowed

        # TODO: insert before id:user_data-change-password
        if _check_allowed(self.context, self.request, 'oauth-preferences'):
            tabs.append({
                'title': u'User Sharing Settings',
                'url': navigation_root_url + '/@@oauth-preferences',
                'selected': (self.__name__ == 'oauth-preferences'),
                'id': 'user_data-oauth-preferences',
            })
        return tabs
